from bplustree import BPlusTree


class Table:
    def __init__(self, name, schema, order=8, search_key=None):
        self.name = name  # Name of the table
        self.schema = schema  # Table schema: dict of {column_name: data_type}
        self.order = order  # Order of the B+ Tree (max number of children)
        self.data = BPlusTree(order=order)  # Underlying B+ Tree to store the data
        self.search_key = search_key  # Primary or search key used for indexing (must be in schema)

        # Default to the first key in the schema if search_key isn't provided
        if search_key is None:
            self.search_key = list(schema.keys())[0]

        if self.search_key not in self.schema:
            raise ValueError(f"Search key '{self.search_key}' must be defined in the schema.")

    def validate_record(self, record):
        """
        Validate that the given record matches the table schema:
        - All required columns are present
        - Data types are correct
        """
        if set(record.keys()) != set(self.schema.keys()):
            return False

        for key, val_type in self.schema.items():
            val = record[key]
            if val_type in (int, float) and isinstance(val, bool):
                return False
            if not isinstance(val, val_type) and not (val_type == float and isinstance(val, int)):
                return False

        return True

    def insert(self, record):
        """
        Insert a new record into the table.
        The record should be a dictionary matching the schema.
        The key used for insertion should be the value of the `search_key` field.
        """
        if not self.validate_record(record):
            return False, "Invalid record schema"

        key = record[self.search_key]
        if self.get(key) is not None:
            return False, f"Primary key '{key}' already exists"

        self.data.insert(key, record)
        return True, key

    def get(self, record_id):
        """
        Retrieve a single record by its ID (i.e., the value of the `search_key`)
        """
        return self.data.search(record_id)

    def get_all(self):
        """
        Retrieve all records stored in the table in sorted order by search key
        """
        return self.data.get_all()

    def update(self, record_id, new_record):
        """
        Update a record identified by `record_id` with `new_record` data.
        Overwrites the existing entry.
        """
        if self.get(record_id) is None:
            return False, "Record not found"

        if not self.validate_record(new_record):
            return False, "Invalid record schema"

        new_key = new_record[self.search_key]

        if record_id != new_key:
            if self.get(new_key) is not None:
                return False, f"New primary key '{new_key}' already exists"

            self.data.delete(record_id)
            self.data.insert(new_key, new_record)
        else:
            self.data.update(new_key, new_record)

        return True, 'Record updated'

    def delete(self, record_id):
        """
        Delete the record from the table by its `record_id`
        """
        success = self.data.delete(record_id)
        if success:
            return True, 'Record deleted'
        return False, 'Record not found'

    def range_query(self, start_value, end_value):
        """
        Perform a range query using the search key.
        Returns records where start_value <= key <= end_value
        """
        return self.data.range_query(start_value, end_value)
