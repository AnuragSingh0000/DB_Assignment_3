from bplustree import BPlusTree

class Table:
    def __init__(self, name, schema, order=8, search_key=None, constraints=None, foreign_keys=None, referenced_by=None):
        self.name = name
        self.schema = schema
        self.order = order
        self.data = BPlusTree(order=order)
        
        # constraints: {'age': {'CHECK': 'x >= 18'}, 'email': {'NOT NULL': True}}
        # Note: CHECK constraints are now strings to allow safe pickling.
        self.constraints = constraints or {}
        
        # foreign_keys: {'user_id': 'Users'}  (Maps local column to target table)
        self.foreign_keys = foreign_keys or {}
        
        # referenced_by: [('Orders', 'user_id')] (List of tuples: (Child Table, Child Column))
        self.referenced_by = referenced_by or []

        self.search_key = search_key 
        if self.search_key is None:
            self.search_key = list(schema.keys())[0]

        if self.search_key not in self.schema:
            raise ValueError(f"Search key '{self.search_key}' must be defined in the schema.")

    def validate_record(self, record, current_pk=None):
        """
        Validate schema, types, and single-table constraints (NOT NULL, UNIQUE, CHECK).
        Does NOT check Foreign Keys (that requires the Transaction Manager).
        """
        # Apply defaults
        for col, rules in self.constraints.items():
            if 'DEFAULT' in rules and col not in record:
                record[col] = rules['DEFAULT']

        if set(record.keys()) != set(self.schema.keys()):
            return False, f"Schema mismatch. Expected {list(self.schema.keys())}"

        for key, val_type in self.schema.items():
            val = record.get(key)
            rules = self.constraints.get(key, {})

            # Type Checking
            if val is not None:
                if val_type in (int, float) and isinstance(val, bool):
                    return False, f"Type mismatch for '{key}'"
                if not isinstance(val, val_type) and not (val_type == float and isinstance(val, int)):
                    return False, f"Type mismatch for '{key}'"

            # NOT NULL Check
            if rules.get('NOT NULL') and val is None:
                return False, f"Constraint Error: '{key}' cannot be NULL"

            # String-based CHECK Constraint Evaluation
            if 'CHECK' in rules and val is not None:
                check_expr = rules['CHECK']
                try:
                    # Evaluate the string expression. 
                    # 'x' represents the current column value, 'record' is the full dictionary.
                    is_valid = eval(check_expr, {}, {"x": val, "record": record})
                    if not is_valid:
                        return False, f"Constraint Error: CHECK failed for '{key}'='{val}'"
                except Exception as e:
                    return False, f"Constraint Error: Failed to evaluate CHECK '{check_expr}' for '{key}': {str(e)}"

            # UNIQUE Check
            if rules.get('UNIQUE') and val is not None:
                for _, existing_rec in self.get_all():
                    if current_pk is not None and existing_rec[self.search_key] == current_pk:
                        continue
                    if existing_rec[key] == val:
                        return False, f"Constraint Error: UNIQUE failed. '{val}' already exists."

        return True, "Valid"

    # --- CRUD Operations ---
    def insert(self, record):
        is_valid, msg = self.validate_record(record)
        if not is_valid: return False, msg

        key = record[self.search_key]
        if self.get(key) is not None:
            return False, f"Primary key '{key}' already exists"

        self.data.insert(key, record)
        return True, key

    def get(self, record_id):
        return self.data.search(record_id)

    def get_all(self):
        return self.data.get_all()

    def update(self, record_id, new_record):
        if self.get(record_id) is None: return False, "Record not found"

        is_valid, msg = self.validate_record(new_record, current_pk=record_id)
        if not is_valid: return False, msg

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
        if self.data.delete(record_id): return True, 'Record deleted'
        return False, 'Record not found'