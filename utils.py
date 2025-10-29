import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="127.0.0.1",
        user="golda",
        password="GoldaKoodaa",
        database="airway666",
        autocommit=True
    )