import mysql.connector

try:
    conn = mysql.connector.connect(
        host="127.0.0.1",           # Local end of your SSH tunnel
    port=3330,                   # Local port forwarded by your tunnel
    user="your_mysql_user",
    password="your_mysql_password",
    database="your_database",
    connection_timeout=5,
    auth_plugin='mysql_native_password'
    )
    print("Connected!")
    conn.close()
except Exception as e:
    print(f"Connection failed: {e}") 
