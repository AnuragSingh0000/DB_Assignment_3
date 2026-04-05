import os
import pickle
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

    # ─── DURABILITY & RECOVERY METHODS ──────────────────────────────────────

    def save_to_disk(self, filepath='database.dat'):
        """
        Saves tables, records, AND all constraint metadata to disk.
        """
        snapshot = {}
        for db_name, tables in self.databases.items():
            snapshot[db_name] = {}
            for tname, table in tables.items():
                snapshot[db_name][tname] = {
                    'schema': table.schema,
                    'order': getattr(table, 'order', 8),           # Safely get order, default 8
                    'search_key': table.search_key,
                    'constraints': getattr(table, 'constraints', {}), 
                    'foreign_keys': getattr(table, 'foreign_keys', {}), 
                    'referenced_by': getattr(table, 'referenced_by', []),
                    'records': list(table.get_all())
                }
        with open(filepath, 'wb') as f:
            pickle.dump(snapshot, f)

    def load_from_disk(self, filepath='database.dat'):
        """
        Restores the complete state including metadata.
        Safely ignores empty or corrupted files.
        """
        import os
        import pickle
        
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return
            
        try:
            with open(filepath, 'rb') as f:
                snapshot = pickle.load(f)
        except (EOFError, pickle.UnpicklingError):
            print(f"Warning: '{filepath}' is corrupted or empty. Starting fresh.")
            return
            
        for db_name, tables in snapshot.items():
            # Create the database if it doesn't exist yet
            if db_name not in self.databases:
                self.create_database(db_name)
                
            for tname, info in tables.items():
                self.create_table(
                    db_name, 
                    tname, 
                    info['schema'], 
                    order=info['order'], 
                    search_key=info['search_key']
                )
                
                tbl, _ = self.get_table(db_name, tname)
                if tbl == None:
                    print(f'Unable to fetch tables')
                    return
                
                # Restore metadata constraints
                tbl.constraints = info['constraints']
                tbl.foreign_keys = info['foreign_keys']
                tbl.referenced_by = info['referenced_by']
                
                # Restore the actual records
                for _, record in info['records']:
                    tbl.insert(record)