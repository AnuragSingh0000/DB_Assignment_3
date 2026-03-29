import os
from bplustree import BPlusTree


def run_insertion_stages():
    bpt = BPlusTree(order=4)

    os.makedirs("../images/insertion_stages", exist_ok=True)

    insert_keys = [10, 20, 5, 6, 12, 30, 7, 17, 3, 25, 15]

    for i, key in enumerate(insert_keys):
        bpt.insert(key, f"val{key}")
        print(f"Inserted {key}")

        path = f"../images/insertion_stages/stage_{i+1}_insert_{key}"
        bpt.visualize_tree(path)
        print(f"Saved: {path}.png")


if __name__ == "__main__":
    run_insertion_stages()