import math
from bisect import bisect_left, bisect_right


class BPlusTreeNode:
    __slots__ = ('is_leaf', 'keys', 'children', 'values', 'next')

    def __init__(self, is_leaf=True):
        self.is_leaf = is_leaf  # Flag to check if node is a leaf
        self.keys = []  # List of keys in the node
        self.values = []  # Used in leaf nodes to store associated values
        self.children = []  # Used in internal nodes to store child pointers
        self.next = None  # Points to next leaf node for range queries


class BPlusTree:
    def __init__(self, order=8):
        self.order = order  # Maximum number of children per internal node
        self.root = BPlusTreeNode()  # Start with an empty leaf node as root
        self.min_keys = math.ceil(order / 2) - 1

    def search(self, key):
        """Search for a key in the B+ tree and return the associated value"""
        return self._search(self.root, key)

    def _search(self, node, key):
        """Helper function to search for a key starting from the given node"""
        curr = node
        # Traverse down to the leaf
        while not curr.is_leaf:
            i = bisect_right(curr.keys, key)
            curr = curr.children[i]

        # Binary search within the leaf node
        i = bisect_left(curr.keys, key)
        if i < len(curr.keys) and curr.keys[i] == key:
            return curr.values[i]
        return None

    def insert(self, key, value):
        """Insert a new key-value pair into the B+ tree"""
        # path acts as an iterative call stack here
        path = []
        curr = self.root

        # Iterative descent to find the leaf:
        while not curr.is_leaf:
            i = bisect_right(curr.keys, key)
            path.append((curr, i))
            curr = curr.children[i]

        # Insert at the leaf
        self._insert_non_full(curr, key, value)

        # Iterative self-balancing:
        while len(curr.keys) >= self.order:
            if not path:
                # Tree height increases when the root splits
                new_root = BPlusTreeNode(is_leaf=False)
                new_root.children.append(self.root)
                self._split_child(new_root, 0)
                self.root = new_root
                break

            # Propagate the split upwards to the parent node
            parent, p_idx = path.pop()
            self._split_child(parent, p_idx)
            curr = parent

    def _insert_non_full(self, node, key, value):
        """Insert key-value into a node that is not full"""
        i = bisect_right(node.keys, key)
        node.keys.insert(i, key)
        node.values.insert(i, value)

    def _split_child(self, parent, index):
        """
        Split the child node at given index in the parent.
        This is triggered when the child is full.
        """
        child = parent.children[index]
        new_node = BPlusTreeNode(is_leaf=child.is_leaf)
        mid = self.min_keys

        if child.is_leaf:
            new_node.keys = child.keys[mid:]
            new_node.values = child.values[mid:]

            del child.keys[mid:]
            del child.values[mid:]

            # Maintain horizontal leaf-node linked list (for range queries)
            new_node.next = child.next
            child.next = new_node

            parent.keys.insert(index, new_node.keys[0])
            parent.children.insert(index + 1, new_node)

        else:
            # Internal nodes promote the middle key (without duplicating it)
            promote_key = child.keys[mid]

            new_node.keys = child.keys[mid + 1:]
            new_node.children = child.children[mid + 1:]

            del child.keys[mid:]
            del child.children[mid + 1:]

            parent.keys.insert(index, promote_key)
            parent.children.insert(index + 1, new_node)

    def delete(self, key):
        """Delete a key from the B+ tree"""
        path = []
        curr = self.root

        # Iterative descent to find the leaf
        while not curr.is_leaf:
            i = bisect_right(curr.keys, key)
            path.append((curr, i))
            curr = curr.children[i]

        # Delete the key
        if not self._delete(curr, key):
            return False

        # If the first element of a leaf is deleted, we must update the parent's routing keys
        # (so that internal searches still correctly point to this node)
        if curr.keys:
            new_first = curr.keys[0]

            for parent, idx in reversed(path):
                if idx > 0:
                    parent.keys[idx - 1] = new_first

        # Iterative self-balancing
        while len(curr.keys) < self.min_keys:
            if not path:
                # Tree height decreases if the root internal node becomes completely empty
                if not curr.is_leaf and len(curr.keys) == 0:
                    self.root = curr.children[0]
                break

            parent, p_idx = path.pop()
            self._fill_child(parent, p_idx)
            curr = parent  # Continue checking for underflow upwards

        return True

    def _delete(self, node, key):
        """Helper function for delete operation"""
        i = bisect_left(node.keys, key)
        if i >= len(node.keys) or node.keys[i] != key:
            return False
        node.keys.pop(i)
        node.values.pop(i)
        return True

    def _fill_child(self, parent, index):
        """Ensure that the child node has enough keys to allow safe deletion"""
        # Borrow from siblings to avoid merge operations
        if index > 0 and len(parent.children[index - 1].keys) > self.min_keys:
            self._borrow_from_prev(parent, index)
        elif index < len(parent.children) - 1 and len(parent.children[index + 1].keys) > self.min_keys:
            self._borrow_from_next(parent, index)
        else:
            # Merge if both siblings are exactly at min_keys
            if index > 0:
                self._merge(parent, index - 1)
            else:
                self._merge(parent, index)

    def _borrow_from_prev(self, parent, index):
        """Borrow a key from the left sibling"""
        child = parent.children[index]
        sibling = parent.children[index - 1]

        if child.is_leaf:
            child.keys.insert(0, sibling.keys.pop())
            child.values.insert(0, sibling.values.pop())
            parent.keys[index - 1] = child.keys[0]  # Update routing key
        else:
            # Internal node borrowing should pull the routing key down from the parent
            child.keys.insert(0, parent.keys[index - 1])
            parent.keys[index - 1] = sibling.keys.pop()
            child.children.insert(0, sibling.children.pop())

    def _borrow_from_next(self, parent, index):
        """Borrow a key from the right sibling"""
        child = parent.children[index]
        sibling = parent.children[index + 1]

        if child.is_leaf:
            child.keys.append(sibling.keys.pop(0))
            child.values.append(sibling.values.pop(0))
            parent.keys[index] = sibling.keys[0]  # Update routing key
        else:
            # Internal node borrowing pushes a key up to the parent
            child.keys.append(parent.keys[index])
            parent.keys[index] = sibling.keys.pop(0)
            child.children.append(sibling.children.pop(0))

    def _merge(self, parent, index):
        """Merge two child nodes into one"""
        left = parent.children[index]
        right = parent.children[index + 1]

        if left.is_leaf:
            left.keys.extend(right.keys)
            left.values.extend(right.values)
            left.next = right.next  # Fix linked list by skipping the merged node
        else:
            # When merging internal nodes, we should pull down the separating routing key
            left.keys.append(parent.keys[index])
            left.keys.extend(right.keys)
            left.children.extend(right.children)

        # Remove the routing key and the right child pointer from the parent
        parent.keys.pop(index)
        parent.children.pop(index + 1)

    def update(self, key, new_value):
        """Update the value associated with a key"""
        curr = self.root
        while not curr.is_leaf:
            i = bisect_right(curr.keys, key)
            curr = curr.children[i]

        i = bisect_left(curr.keys, key)
        if i < len(curr.keys) and curr.keys[i] == key:
            curr.values[i] = new_value
            return True

        return False

    def range_query(self, start_key, end_key):
        """
        Return all key-value pairs where start_key <= key <= end_key.
        Utilizes the linked list structure of leaf nodes.
        """
        if start_key > end_key:
            return []

        curr = self.root
        # Find the leaf containing the start boundary
        while not curr.is_leaf:
            i = bisect_right(curr.keys, start_key)
            curr = curr.children[i]

        results = []
        i = bisect_left(curr.keys, start_key)

        # Go through the linked list sequentially
        while curr is not None:
            while i < len(curr.keys):
                k = curr.keys[i]
                if k <= end_key:
                    results.append((k, curr.values[i]))
                else:
                    return results  # Finish early once out of bounds
                i += 1
            i = 0  # Reset for future nodes
            curr = curr.next

        return results

    def get_all(self):
        """Get all key-value pairs in the tree in sorted order"""
        results = []
        self._get_all(self.root, results)
        return results

    def _get_all(self, node, result):
        """Helper function to gather all key-value pairs"""
        curr = node
        # Go to the leftmost leaf
        while not curr.is_leaf:
            curr = curr.children[0]

        # Go through the whole linked list
        while curr is not None:
            for i in range(len(curr.keys)):
                result.append((curr.keys[i], curr.values[i]))
            curr = curr.next

    def visualize_tree(self, filename="bplustree"):
        """
        Visualize the tree using graphviz.
        Optional filename can be provided to save the output.
        """
        return TreeVisualizer.visualize(self, filename)


class TreeVisualizer:
    @staticmethod
    def visualize(tree, filename="bplustree"):
        try:
            from graphviz import Digraph
        except ImportError:
            print("Graphviz not installed. Run: pip install graphviz")
            return None

        dot = Digraph()
        dot.attr(rankdir="TB")
        dot.attr(nodesep="0.4", ranksep="0.5")

        node_map = {}
        node_id = [0]

        def traverse(node):
            curr_id = f"node{node_id[0]}"
            node_map[node] = curr_id
            node_id[0] += 1

            if node.keys:
                label = " | ".join(str(k) for k in node.keys)
            else:
                label = "Empty"

            if node.is_leaf:
                dot.node(curr_id, label=label, shape="record", style="filled", fillcolor="lightgreen")
            else:
                dot.node(curr_id, label=label, shape="record", style="filled", fillcolor="lightblue")

            if not node.is_leaf:
                for child in node.children:
                    child_id = traverse(child)
                    dot.edge(curr_id, child_id)

            return curr_id

        if tree.root:
            traverse(tree.root)

        curr = tree.root
        while not curr.is_leaf:
            curr = curr.children[0]

        while curr and curr.next:
            dot.edge(node_map[curr], node_map[curr.next], style="dashed", color="darkgreen")
            curr = curr.next

        dot.render(filename, format="png", cleanup=True)
        return dot
