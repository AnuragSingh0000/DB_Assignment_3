from table import Table


class DatabaseManager:
    def __init__(self):
        self.databases = {}  # Dictionary to store databases as {db_name: {table_name: Table instance}}

    def create_database(self, db_name):
        """
        Create a new database with the given name.
        Initializes an empty dictionary for tables within this database.
        """
        if db_name in self.databases:
            return False, f"Database '{db_name}' already exists"
        self.databases[db_name] = {}
        return True, f"Database '{db_name}' created successfully"

    def delete_database(self, db_name):
        """
        Delete an existing database and all its tables.
        """
        if db_name in self.databases:
            del self.databases[db_name]
            return True, f"Database '{db_name}' deleted successfully"
        return False, f"Database '{db_name}' does not exist"

    def list_databases(self):
        """
        Return a list of all database names currently managed.
        """
        return list(self.databases.keys())

    def create_table(self, db_name, table_name, schema, order=8, search_key=None):
        """
        Create a new table within a specified database.
        - schema: dictionary of column names and data types
        - order: B+ tree order for indexing
        - search_key: field name to use as the key in the B+ Tree
        """
        if db_name not in self.databases:
            return False, f"Database '{db_name}' does not exist"
        if table_name in self.databases[db_name]:
            return False, f"Table '{table_name}' already exists"

        new_table = Table(table_name, schema, order, search_key)
        self.databases[db_name][table_name] = new_table
        return True, f"Table '{table_name}' created successfully in database '{db_name}'"

    def delete_table(self, db_name, table_name):
        """
        Delete a table from the specified database.
        """
        if db_name in self.databases and table_name in self.databases[db_name]:
            del self.databases[db_name][table_name]
            return True, f"Table '{table_name}' deleted successfully"
        return False, "Database or Table does not exist"

    def list_tables(self, db_name):
        """
        List all tables within a given database.
        """
        if db_name in self.databases:
            return list(self.databases[db_name].keys()), "Success"
        return [], "Database does not exist"

    def get_table(self, db_name, table_name):
        """
        Retrieve a Table instance from a given database.
        Useful for performing operations like insert, update, delete on that table.
        """
        if db_name in self.databases and table_name in self.databases[db_name]:
            return self.databases[db_name][table_name], "Success"
        return None, "Database or Table does not exist"
