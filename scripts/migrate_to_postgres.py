#!/usr/bin/env python3
import asyncio
import aiosqlite
import asyncpg
import os
import sys
from datetime import datetime
from loguru import logger


SQLITE_DB_PATH = "data/learning.db"
POSTGRES_URL = os.getenv("DATABASE_URL", "postgresql://trader:password@localhost:5240/trading_bot")

TABLES = ["models", "training_runs", "predictions", "balance_history"]


async def check_sqlite_exists():
    if not os.path.exists(SQLITE_DB_PATH):
        logger.error(f"SQLite database not found at {SQLITE_DB_PATH}")
        return False
    
    file_size = os.path.getsize(SQLITE_DB_PATH)
    logger.info(f"SQLite database found: {file_size:,} bytes")
    return True


async def backup_sqlite():
    backup_path = f"{SQLITE_DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        import shutil
        shutil.copy2(SQLITE_DB_PATH, backup_path)
        logger.info(f"SQLite backup created: {backup_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to create backup: {e}")
        return False


async def count_sqlite_rows(conn, table):
    async with conn.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
        result = await cursor.fetchone()
        return result[0] if result else 0


async def get_sqlite_columns(conn, table):
    async with conn.execute(f"PRAGMA table_info({table})") as cursor:
        rows = await cursor.fetchall()
        return [row[1] for row in rows]


async def migrate_table(sqlite_conn, pg_pool, table):
    logger.info(f"Migrating table: {table}")
    
    row_count = await count_sqlite_rows(sqlite_conn, table)
    if row_count == 0:
        logger.info(f"  {table}: No data to migrate")
        return True
    
    logger.info(f"  {table}: {row_count:,} rows to migrate")
    
    columns = await get_sqlite_columns(sqlite_conn, table)
    logger.info(f"  Columns: {', '.join(columns)}")
    
    async with sqlite_conn.execute(f"SELECT * FROM {table}") as cursor:
        rows = await cursor.fetchall()
    
    async with pg_pool.acquire() as conn:
        migrated = 0
        failed = 0
        
        for row in rows:
            try:
                placeholders = ','.join([f'${i+1}' for i in range(len(row))])
                query = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
                
                processed_row = []
                for val in row:
                    if isinstance(val, bool):
                        processed_row.append(val)
                    elif val is None:
                        processed_row.append(None)
                    else:
                        processed_row.append(val)
                
                await conn.execute(query, *processed_row)
                migrated += 1
                
                if migrated % 100 == 0:
                    logger.info(f"  Progress: {migrated}/{row_count} rows migrated")
                    
            except Exception as e:
                failed += 1
                logger.error(f"  Failed to migrate row: {e}")
                if failed > 10:
                    logger.error(f"  Too many failures, aborting {table}")
                    return False
        
        logger.info(f"  ✅ {table}: {migrated:,} rows migrated, {failed} failed")
        return True


async def verify_migration(sqlite_conn, pg_pool, table):
    sqlite_count = await count_sqlite_rows(sqlite_conn, table)
    
    async with pg_pool.acquire() as conn:
        pg_count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
    
    match = sqlite_count == pg_count
    status = "✅" if match else "❌"
    logger.info(f"  {status} {table}: SQLite={sqlite_count:,}, PostgreSQL={pg_count:,}")
    
    return match


async def main():
    logger.info("=" * 60)
    logger.info("SQLite to PostgreSQL Migration")
    logger.info("=" * 60)
    
    if not await check_sqlite_exists():
        sys.exit(1)
    
    logger.info(f"Target PostgreSQL: {POSTGRES_URL.split('@')[1]}")
    
    response = input("\nCreate backup before migration? (Y/n): ")
    if response.lower() != 'n':
        if not await backup_sqlite():
            sys.exit(1)
    
    response = input("\nProceed with migration? (y/N): ")
    if response.lower() != 'y':
        logger.info("Migration cancelled")
        sys.exit(0)
    
    logger.info("\n" + "=" * 60)
    logger.info("Starting Migration")
    logger.info("=" * 60)
    
    try:
        sqlite_conn = await aiosqlite.connect(SQLITE_DB_PATH)
        pg_pool = await asyncpg.create_pool(
            POSTGRES_URL.replace("postgresql+asyncpg://", "postgresql://"),
            min_size=1,
            max_size=5
        )
        
        logger.info("\n📊 Row counts in SQLite:")
        for table in TABLES:
            count = await count_sqlite_rows(sqlite_conn, table)
            logger.info(f"  {table}: {count:,} rows")
        
        logger.info("\n🔄 Migrating data...")
        all_success = True
        for table in TABLES:
            success = await migrate_table(sqlite_conn, pg_pool, table)
            if not success:
                all_success = False
                break
        
        if all_success:
            logger.info("\n✅ Verifying migration...")
            all_verified = True
            for table in TABLES:
                if not await verify_migration(sqlite_conn, pg_pool, table):
                    all_verified = False
            
            if all_verified:
                logger.info("\n" + "=" * 60)
                logger.info("✅ MIGRATION SUCCESSFUL")
                logger.info("=" * 60)
                logger.info("\nNext steps:")
                logger.info("1. Update DATABASE_URL in .env file")
                logger.info("2. Restart all services: docker-compose down && docker-compose up -d")
                logger.info("3. Test with: python -c 'from learning.database_postgres import PostgresDatabase; import asyncio; db = PostgresDatabase(); asyncio.run(db.initialize())'")
            else:
                logger.error("\n❌ MIGRATION VERIFICATION FAILED")
                logger.error("Please review the logs and verify data manually")
        else:
            logger.error("\n❌ MIGRATION FAILED")
            logger.error("Some tables could not be migrated. Check logs above.")
        
        await sqlite_conn.close()
        await pg_pool.close()
        
    except Exception as e:
        logger.error(f"\n❌ Migration error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
