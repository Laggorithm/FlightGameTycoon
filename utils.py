import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="Salasana2025",
        database="airway666",
        autocommit=True
    )