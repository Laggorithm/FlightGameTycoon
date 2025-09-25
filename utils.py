import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="golda",
        password="GoldaKoodaa",
        database="airway666",
        autocommit=True
    )