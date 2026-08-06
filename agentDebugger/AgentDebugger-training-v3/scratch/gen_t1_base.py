import json

t1_bugs = []

funcs = [
    {
        "name": "factorial",
        "orig": "def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n - 1)",
        "cases": [{"input": 0, "expected_output": 1}, {"input": 1, "expected_output": 1}, {"input": 5, "expected_output": 120}, {"input": 3, "expected_output": 6}]
    },
    {
        "name": "fibonacci",
        "orig": "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)",
        "cases": [{"input": 0, "expected_output": 0}, {"input": 1, "expected_output": 1}, {"input": 5, "expected_output": 5}, {"input": 7, "expected_output": 13}]
    },
    {
        "name": "string_reverse",
        "orig": "def string_reverse(s):\n    return s[::-1]",
        "cases": [{"input": "hello", "expected_output": "olleh"}, {"input": "", "expected_output": ""}, {"input": "a", "expected_output": "a"}, {"input": "racecar", "expected_output": "racecar"}]
    },
    {
        "name": "count_occurrences",
        "orig": "def count_occurrences(lst, target):\n    count = 0\n    for item in lst:\n        if item == target:\n            count += 1\n    return count",
        "cases": [{"input": [[1,2,1,3,1], 1], "expected_output": 3}, {"input": [[], 5], "expected_output": 0}, {"input": [[2,2,2], 2], "expected_output": 3}, {"input": [[1,2,3], 4], "expected_output": 0}]
    },
    {
        "name": "sum_digits",
        "orig": "def sum_digits(n):\n    total = 0\n    while n > 0:\n        total += n % 10\n        n //= 10\n    return total",
        "cases": [{"input": 123, "expected_output": 6}, {"input": 0, "expected_output": 0}, {"input": 999, "expected_output": 27}, {"input": 10, "expected_output": 1}]
    },
    {
        "name": "is_prime",
        "orig": "def is_prime(n):\n    if n <= 1:\n        return False\n    for i in range(2, int(n**0.5) + 1):\n        if n % i == 0:\n            return False\n    return True",
        "cases": [{"input": 2, "expected_output": True}, {"input": 4, "expected_output": False}, {"input": 13, "expected_output": True}, {"input": 1, "expected_output": False}]
    },
    {
        "name": "merge_intervals",
        "orig": "def merge_intervals(intervals):\n    if not intervals:\n        return []\n    intervals.sort(key=lambda x: x[0])\n    merged = [intervals[0]]\n    for current in intervals:\n        previous = merged[-1]\n        if current[0] <= previous[1]:\n            previous[1] = max(previous[1], current[1])\n        else:\n            merged.append(current)\n    return merged",
        "cases": [{"input": [[[1,3],[2,6],[8,10],[15,18]]], "expected_output": [[1,6],[8,10],[15,18]]}, {"input": [[[1,4],[4,5]]], "expected_output": [[1,5]]}, {"input": [[]], "expected_output": []}, {"input": [[[1,4],[0,4]]], "expected_output": [[0,4]]}]
    },
    {
        "name": "remove_duplicates",
        "orig": "def remove_duplicates(nums):\n    if not nums:\n        return 0\n    i = 0\n    for j in range(1, len(nums)):\n        if nums[j] != nums[i]:\n            i += 1\n            nums[i] = nums[j]\n    return i + 1",
        "cases": [{"input": [[1,1,2]], "expected_output": 2}, {"input": [[0,0,1,1,1,2,2,3,3,4]], "expected_output": 5}, {"input": [[]], "expected_output": 0}, {"input": [[1]], "expected_output": 1}]
    },
    {
        "name": "longest_common_prefix",
        "orig": "def longest_common_prefix(strs):\n    if not strs:\n        return \"\"\n    prefix = strs[0]\n    for s in strs[1:]:\n        while not s.startswith(prefix):\n            prefix = prefix[:-1]\n            if not prefix:\n                return \"\"\n    return prefix",
        "cases": [{"input": [["flower","flow","flight"]], "expected_output": "fl"}, {"input": [["dog","racecar","car"]], "expected_output": ""}, {"input": [[]], "expected_output": ""}, {"input": [["a"]], "expected_output": "a"}]
    },
    {
        "name": "product_except_self",
        "orig": "def product_except_self(nums):\n    n = len(nums)\n    res = [1] * n\n    prefix = 1\n    for i in range(n):\n        res[i] = prefix\n        prefix *= nums[i]\n    postfix = 1\n    for i in range(n - 1, -1, -1):\n        res[i] *= postfix\n        postfix *= nums[i]\n    return res",
        "cases": [{"input": [[1,2,3,4]], "expected_output": [24,12,8,6]}, {"input": [[-1,1,0,-3,3]], "expected_output": [0,0,9,0,0]}, {"input": [[2,3]], "expected_output": [3,2]}, {"input": [[1,1,1]], "expected_output": [1,1,1]}]
    },
    {
        "name": "valid_parentheses",
        "orig": "def valid_parentheses(s):\n    stack = []\n    mapping = {')': '(', '}': '{', ']': '['}\n    for char in s:\n        if char in mapping:\n            top_element = stack.pop() if stack else '#'\n            if mapping[char] != top_element:\n                return False\n        else:\n            stack.append(char)\n    return not stack",
        "cases": [{"input": "()", "expected_output": True}, {"input": "()[]{}", "expected_output": True}, {"input": "(]", "expected_output": False}, {"input": "([)]", "expected_output": False}]
    },
    {
        "name": "climbing_stairs",
        "orig": "def climbing_stairs(n):\n    if n <= 2:\n        return n\n    a, b = 1, 2\n    for _ in range(3, n + 1):\n        a, b = b, a + b\n    return b",
        "cases": [{"input": 2, "expected_output": 2}, {"input": 3, "expected_output": 3}, {"input": 1, "expected_output": 1}, {"input": 5, "expected_output": 8}]
    },
    {
        "name": "house_robber",
        "orig": "def house_robber(nums):\n    if not nums:\n        return 0\n    if len(nums) == 1:\n        return nums[0]\n    dp = [0] * len(nums)\n    dp[0] = nums[0]\n    dp[1] = max(nums[0], nums[1])\n    for i in range(2, len(nums)):\n        dp[i] = max(dp[i-1], dp[i-2] + nums[i])\n    return dp[-1]",
        "cases": [{"input": [[1,2,3,1]], "expected_output": 4}, {"input": [[2,7,9,3,1]], "expected_output": 12}, {"input": [[]], "expected_output": 0}, {"input": [[5]], "expected_output": 5}]
    },
    {
        "name": "intersection_of_arrays",
        "orig": "def intersection_of_arrays(nums1, nums2):\n    return list(set(nums1) & set(nums2))",
        "cases": [{"input": [[1,2,2,1], [2,2]], "expected_output": [2]}, {"input": [[4,9,5], [9,4,9,8,4]], "expected_output": [9,4]}, {"input": [[], [1]], "expected_output": []}, {"input": [[1,2], [3,4]], "expected_output": []}]
    },
    {
        "name": "group_anagrams",
        "orig": "def group_anagrams(strs):\n    from collections import defaultdict\n    ans = defaultdict(list)\n    for s in strs:\n        ans[tuple(sorted(s))].append(s)\n    return list(ans.values())",
        "cases": [{"input": [["eat","tea","tan","ate","nat","bat"]], "expected_output": [["eat","tea","ate"],["tan","nat"],["bat"]]}, {"input": [[""]], "expected_output": [[""]]}, {"input": [["a"]], "expected_output": [["a"]]}, {"input": [["ab", "ba"]], "expected_output": [["ab", "ba"]]}]
    }
]


bug_id_counter = 9
for f in funcs:
    for i in range(2):
        bug = {
            "id": f"t1_{bug_id_counter:03d}",
            "difficulty": 1,
            "bug_type": "logic_error",
            "function_name": f["name"],
            "original_code": f["orig"],
            "test_cases": f["cases"],
            "initial_error": "AssertionError: function failed",
            "bug_location": {"function": f["name"], "line_start": 2}
        }
        
        
        
        t1_bugs.append(bug)
        bug_id_counter += 1


for i in range(2):
    bug = {
        "id": f"t1_{bug_id_counter:03d}",
        "difficulty": 1,
        "bug_type": "logic_error",
        "function_name": funcs[0]["name"],
        "original_code": funcs[0]["orig"],
        "test_cases": funcs[0]["cases"],
        "initial_error": "AssertionError: function failed",
        "bug_location": {"function": funcs[0]["name"], "line_start": 2}
    }
    t1_bugs.append(bug)
    bug_id_counter += 1

with open("scratch/t1_base.json", "w") as f:
    json.dump(t1_bugs, f, indent=4)
