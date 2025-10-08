import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="Laggorithm",
        password="CupOfLiberTea",
        database="airway666",
        autocommit=True
    )