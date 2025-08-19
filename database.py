import psycopg2

try:
    conn = psycopg2.connect(
        host="localhost",
        database="store_inventory",
        user="postgres",
        password="Adilkhan69"
    )
    print("✅ Connected successfully!")
    conn.close()
except Exception as e:
    print("❌ Connection failed:", e)
