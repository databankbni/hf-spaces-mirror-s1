"""
AgentDebuggerEnv - Bug Dataset Generator

Generates three tiers of buggy Python functions for curriculum learning:
  Tier 1 (easy):   Off-by-one errors, wrong operators, simple logic inversions
  Tier 2 (medium): Incorrect algorithm logic, wrong variable references, subtle type errors
  Tier 3 (hard):   Multi-bug interactions, concurrency, edge-case-only failures

Usage:
  python data/generate_bugs.py

Outputs:
  data/bugs_tier1.jsonl  (~40 bugs)
  data/bugs_tier2.jsonl  (~30 bugs)
  data/bugs_tier3.jsonl  (~20 bugs)
"""

import json
import os

TIER1_BUGS = [{'id': 't1_001',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'binary_search',
  'buggy_code': 'def binary_search(arr, target):\n'
                '    left, right = 0, len(arr)\n'
                '    while left < right:\n'
                '        mid = (left + right) // 2\n'
                '        if arr[mid] == target:\n'
                '            return mid\n'
                '        elif arr[mid] < target:\n'
                '            left = mid + 1\n'
                '        else:\n'
                '            right = mid + 1 + 1 + 1\n'
                '    return -1',
  'original_code': 'def binary_search(arr, target):\n'
                   '    left, right = 0, len(arr) - 1\n'
                   '    while left <= right:\n'
                   '        mid = (left + right) // 2\n'
                   '        if arr[mid] == target:\n'
                   '            return mid\n'
                   '        elif arr[mid] < target:\n'
                   '            left = mid + 1\n'
                   '        else:\n'
                   '            right = mid - 1\n'
                   '    return -1',
  'initial_error': 'IndexError: list index out of range on line 5',
  'bug_location': {'function': 'binary_search', 'line_start': 2},
  'test_cases': [{'input': [[1, 3, 5, 7, 9], 5], 'expected_output': 2},
                 {'input': [[1, 3, 5, 7, 9], 1], 'expected_output': 0},
                 {'input': [[1, 3, 5, 7, 9], 9], 'expected_output': 4},
                 {'input': [[1, 3, 5, 7, 9], 4], 'expected_output': -1}]},
 {'id': 't1_002',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'is_palindrome',
  'buggy_code': 'def is_palindrome(s):\n    return s == s[::-1] and len(s) > 0',
  'original_code': 'def is_palindrome(s):\n    return s == s[::-1]',
  'initial_error': "AssertionError: is_palindrome('') expected True, got False",
  'bug_location': {'function': 'is_palindrome', 'line_start': 2},
  'test_cases': [{'input': ['racecar'], 'expected_output': True},
                 {'input': ['hello'], 'expected_output': False},
                 {'input': [''], 'expected_output': True},
                 {'input': ['a'], 'expected_output': True}]},
 {'id': 't1_003',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'find_max',
  'buggy_code': 'def find_max(nums):\n'
                '    max_val = nums[0]\n'
                '    for i in range(1, len(nums) + 1):\n'
                '        if nums[i] > max_val:\n'
                '            max_val = nums[i]\n'
                '    return max_val',
  'original_code': 'def find_max(nums):\n'
                   '    max_val = nums[0]\n'
                   '    for i in range(1, len(nums)):\n'
                   '        if nums[i] > max_val:\n'
                   '            max_val = nums[i]\n'
                   '    return max_val',
  'initial_error': 'IndexError: list index out of range on line 4',
  'bug_location': {'function': 'find_max', 'line_start': 3},
  'test_cases': [{'input': [[3, 1, 4, 1, 5, 9]], 'expected_output': 9},
                 {'input': [[1]], 'expected_output': 1},
                 {'input': [[-5, -1, -3]], 'expected_output': -1},
                 {'input': [[7, 7, 7]], 'expected_output': 7}]},
 {'id': 't1_004',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'count_vowels',
  'buggy_code': 'def count_vowels(s):\n'
                '    count = 0\n'
                '    for ch in s:\n'
                "        if ch in 'aeiou':\n"
                '            count += 1\n'
                '    return count',
  'original_code': 'def count_vowels(s):\n'
                   '    count = 0\n'
                   '    for ch in s.lower():\n'
                   "        if ch in 'aeiou':\n"
                   '            count += 1\n'
                   '    return count',
  'initial_error': "AssertionError: count_vowels('Hello') expected 2, got 1",
  'bug_location': {'function': 'count_vowels', 'line_start': 3},
  'test_cases': [{'input': ['hello'], 'expected_output': 2},
                 {'input': ['Hello'], 'expected_output': 2},
                 {'input': ['AEIOU'], 'expected_output': 5},
                 {'input': ['xyz'], 'expected_output': 0}]},
 {'id': 't1_005',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'sum_list',
  'buggy_code': 'def sum_list(nums):\n'
                '    total = 0\n'
                '    for i in range(len(nums) - 1):\n'
                '        total += nums[i]\n'
                '    return total',
  'original_code': 'def sum_list(nums):\n'
                   '    total = 0\n'
                   '    for i in range(len(nums)):\n'
                   '        total += nums[i]\n'
                   '    return total',
  'initial_error': 'AssertionError: sum_list([1,2,3]) expected 6, got 3',
  'bug_location': {'function': 'sum_list', 'line_start': 3},
  'test_cases': [{'input': [[1, 2, 3]], 'expected_output': 6},
                 {'input': [[0]], 'expected_output': 0},
                 {'input': [[10, 20, 30, 40]], 'expected_output': 100},
                 {'input': [[]], 'expected_output': 0}]},
 {'id': 't1_006',
  'difficulty': 1,
  'bug_type': 'wrong_comparison',
  'function_name': 'is_sorted',
  'buggy_code': 'def is_sorted(lst):\n'
                '    for i in range(len(lst) - 1):\n'
                '        if lst[i] > lst[i + 1]:\n'
                '            return True\n'
                '    return False',
  'original_code': 'def is_sorted(lst):\n'
                   '    for i in range(len(lst) - 1):\n'
                   '        if lst[i] > lst[i + 1]:\n'
                   '            return False\n'
                   '    return True',
  'initial_error': 'AssertionError: is_sorted([1,2,3]) expected True, got False',
  'bug_location': {'function': 'is_sorted', 'line_start': 4},
  'test_cases': [{'input': [[1, 2, 3]], 'expected_output': True},
                 {'input': [[3, 1, 2]], 'expected_output': False},
                 {'input': [[1]], 'expected_output': True},
                 {'input': [[2, 2, 2]], 'expected_output': True}]},
 {'id': 't1_007',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'factorial',
  'buggy_code': 'def factorial(n):\n'
                '    if n == 0:\n'
                '        return 0\n'
                '    result = 1\n'
                '    for i in range(1, n + 1):\n'
                '        result *= i\n'
                '    return result',
  'original_code': 'def factorial(n):\n'
                   '    if n == 0:\n'
                   '        return 1\n'
                   '    result = 1\n'
                   '    for i in range(1, n + 1):\n'
                   '        result *= i\n'
                   '    return result',
  'initial_error': 'AssertionError: factorial(0) expected 1, got 0',
  'bug_location': {'function': 'factorial', 'line_start': 3},
  'test_cases': [{'input': [0], 'expected_output': 1},
                 {'input': [1], 'expected_output': 1},
                 {'input': [5], 'expected_output': 120},
                 {'input': [3], 'expected_output': 6}]},
 {'id': 't1_008',
  'difficulty': 1,
  'bug_type': 'logic_inversion',
  'function_name': 'is_even',
  'buggy_code': 'def is_even(n):\n    return n % 2 != 0',
  'original_code': 'def is_even(n):\n    return n % 2 == 0',
  'initial_error': 'AssertionError: is_even(4) expected True, got False',
  'bug_location': {'function': 'is_even', 'line_start': 2},
  'test_cases': [{'input': [4], 'expected_output': True},
                 {'input': [3], 'expected_output': False},
                 {'input': [0], 'expected_output': True},
                 {'input': [-2], 'expected_output': True}]},
 {'id': 't1_009',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'factorial',
  'buggy_code': 'def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n)',
  'original_code': 'def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n - 1)',
  'initial_error': 'RecursionError: maximum recursion depth exceeded',
  'bug_location': {'function': 'factorial', 'line_start': 4},
  'test_cases': [{'input': [0], 'expected_output': 1},
                 {'input': [1], 'expected_output': 1},
                 {'input': [5], 'expected_output': 120},
                 {'input': [3], 'expected_output': 6}]},
 {'id': 't1_010',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'factorial',
  'buggy_code': 'def factorial(n):\n    if n == 0:\n        return 1\n    return n + factorial(n - 1)',
  'original_code': 'def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n - 1)',
  'initial_error': 'AssertionError: factorial(3) expected 6, got 6 - wait got 7',
  'bug_location': {'function': 'factorial', 'line_start': 4},
  'test_cases': [{'input': [0], 'expected_output': 1},
                 {'input': [1], 'expected_output': 1},
                 {'input': [5], 'expected_output': 120},
                 {'input': [3], 'expected_output': 6}]},
 {'id': 't1_011',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'fibonacci',
  'buggy_code': 'def fibonacci(n):\n    if n < 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)',
  'original_code': 'def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)',
  'initial_error': 'RecursionError: maximum recursion depth exceeded',
  'bug_location': {'function': 'fibonacci', 'line_start': 2},
  'test_cases': [{'input': [0], 'expected_output': 0},
                 {'input': [1], 'expected_output': 1},
                 {'input': [5], 'expected_output': 5},
                 {'input': [7], 'expected_output': 13}]},
 {'id': 't1_012',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'fibonacci',
  'buggy_code': 'def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) * fibonacci(n-2)',
  'original_code': 'def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)',
  'initial_error': 'AssertionError: fibonacci(5) expected 5, got 0',
  'bug_location': {'function': 'fibonacci', 'line_start': 4},
  'test_cases': [{'input': [0], 'expected_output': 0},
                 {'input': [1], 'expected_output': 1},
                 {'input': [5], 'expected_output': 5},
                 {'input': [7], 'expected_output': 13}]},
 {'id': 't1_013',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'string_reverse',
  'buggy_code': 'def string_reverse(s):\n    return s[:-1]',
  'original_code': 'def string_reverse(s):\n    return s[::-1]',
  'initial_error': "AssertionError: string_reverse('hello') expected 'olleh', got 'hell'",
  'bug_location': {'function': 'string_reverse', 'line_start': 2},
  'test_cases': [{'input': ['hello'], 'expected_output': 'olleh'},
                 {'input': [''], 'expected_output': ''},
                 {'input': ['a'], 'expected_output': 'a'},
                 {'input': ['racecar'], 'expected_output': 'racecar'}]},
 {'id': 't1_014',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'string_reverse',
  'buggy_code': 'def string_reverse(s):\n    return s[1:]',
  'original_code': 'def string_reverse(s):\n    return s[::-1]',
  'initial_error': "AssertionError: string_reverse('hello') expected 'olleh', got 'ello'",
  'bug_location': {'function': 'string_reverse', 'line_start': 2},
  'test_cases': [{'input': ['hello'], 'expected_output': 'olleh'},
                 {'input': [''], 'expected_output': ''},
                 {'input': ['a'], 'expected_output': 'a'},
                 {'input': ['racecar'], 'expected_output': 'racecar'}]},
 {'id': 't1_015',
  'difficulty': 1,
  'bug_type': 'wrong_comparison',
  'function_name': 'count_occurrences',
  'buggy_code': 'def count_occurrences(lst, target):\n'
                '    count = 0\n'
                '    for item in lst:\n'
                '        if item != target:\n'
                '            count += 1\n'
                '    return count',
  'original_code': 'def count_occurrences(lst, target):\n'
                   '    count = 0\n'
                   '    for item in lst:\n'
                   '        if item == target:\n'
                   '            count += 1\n'
                   '    return count',
  'initial_error': 'AssertionError: count_occurrences([1,2,1,3,1], 1) expected 3, got 2',
  'bug_location': {'function': 'count_occurrences', 'line_start': 4},
  'test_cases': [{'input': [[1, 2, 1, 3, 1], 1], 'expected_output': 3},
                 {'input': [[], 5], 'expected_output': 0},
                 {'input': [[2, 2, 2], 2], 'expected_output': 3},
                 {'input': [[1, 2, 3], 4], 'expected_output': 0}]},
 {'id': 't1_016',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'count_occurrences',
  'buggy_code': 'def count_occurrences(lst, target):\n'
                '    count = 1\n'
                '    for item in lst:\n'
                '        if item == target:\n'
                '            count += 1\n'
                '    return count',
  'original_code': 'def count_occurrences(lst, target):\n'
                   '    count = 0\n'
                   '    for item in lst:\n'
                   '        if item == target:\n'
                   '            count += 1\n'
                   '    return count',
  'initial_error': 'AssertionError: count_occurrences([], 5) expected 0, got 1',
  'bug_location': {'function': 'count_occurrences', 'line_start': 2},
  'test_cases': [{'input': [[1, 2, 1, 3, 1], 1], 'expected_output': 3},
                 {'input': [[], 5], 'expected_output': 0},
                 {'input': [[2, 2, 2], 2], 'expected_output': 3},
                 {'input': [[1, 2, 3], 4], 'expected_output': 0}]},
 {'id': 't1_017',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'sum_digits',
  'buggy_code': 'def sum_digits(n):\n'
                '    total = 0\n'
                '    while n > 0:\n'
                '        total += n // 10\n'
                '        n //= 10\n'
                '    return total',
  'original_code': 'def sum_digits(n):\n'
                   '    total = 0\n'
                   '    while n > 0:\n'
                   '        total += n % 10\n'
                   '        n //= 10\n'
                   '    return total',
  'initial_error': 'AssertionError: sum_digits(123) expected 6, got 13',
  'bug_location': {'function': 'sum_digits', 'line_start': 4},
  'test_cases': [{'input': [123], 'expected_output': 6},
                 {'input': [0], 'expected_output': 0},
                 {'input': [999], 'expected_output': 27},
                 {'input': [10], 'expected_output': 1}]},
 {'id': 't1_018',
  'difficulty': 1,
  'bug_type': 'logic_inversion',
  'function_name': 'sum_digits',
  'buggy_code': 'def sum_digits(n):\n'
                '    total = 0\n'
                '    while n < 0:\n'
                '        total += n % 10\n'
                '        n //= 10\n'
                '    return total',
  'original_code': 'def sum_digits(n):\n'
                   '    total = 0\n'
                   '    while n > 0:\n'
                   '        total += n % 10\n'
                   '        n //= 10\n'
                   '    return total',
  'initial_error': 'AssertionError: sum_digits(123) expected 6, got 0',
  'bug_location': {'function': 'sum_digits', 'line_start': 3},
  'test_cases': [{'input': [123], 'expected_output': 6},
                 {'input': [0], 'expected_output': 0},
                 {'input': [999], 'expected_output': 27},
                 {'input': [10], 'expected_output': 1}]},
 {'id': 't1_019',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'is_prime',
  'buggy_code': 'def is_prime(n):\n'
                '    if n < 1:\n'
                '        return False\n'
                '    for i in range(2, int(n**0.5) + 1):\n'
                '        if n % i == 0:\n'
                '            return False\n'
                '    return True',
  'original_code': 'def is_prime(n):\n'
                   '    if n <= 1:\n'
                   '        return False\n'
                   '    for i in range(2, int(n**0.5) + 1):\n'
                   '        if n % i == 0:\n'
                   '            return False\n'
                   '    return True',
  'initial_error': 'AssertionError: is_prime(1) expected False, got True',
  'bug_location': {'function': 'is_prime', 'line_start': 2},
  'test_cases': [{'input': [2], 'expected_output': True},
                 {'input': [4], 'expected_output': False},
                 {'input': [13], 'expected_output': True},
                 {'input': [1], 'expected_output': False}]},
 {'id': 't1_020',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'is_prime',
  'buggy_code': 'def is_prime(n):\n'
                '    if n <= 1:\n'
                '        return False\n'
                '    for i in range(2, int(n**0.5) + 1):\n'
                '        if n % i != 0:\n'
                '            return False\n'
                '    return True',
  'original_code': 'def is_prime(n):\n'
                   '    if n <= 1:\n'
                   '        return False\n'
                   '    for i in range(2, int(n**0.5) + 1):\n'
                   '        if n % i == 0:\n'
                   '            return False\n'
                   '    return True',
  'initial_error': 'AssertionError: is_prime(13) expected True, got False',
  'bug_location': {'function': 'is_prime', 'line_start': 5},
  'test_cases': [{'input': [2], 'expected_output': True},
                 {'input': [4], 'expected_output': False},
                 {'input': [13], 'expected_output': True},
                 {'input': [1], 'expected_output': False}]},
 {'id': 't1_021',
  'difficulty': 1,
  'bug_type': 'wrong_comparison',
  'function_name': 'merge_intervals',
  'buggy_code': 'def merge_intervals(intervals):\n'
                '    if not intervals:\n'
                '        return []\n'
                '    intervals.sort(key=lambda x: x[0])\n'
                '    merged = [intervals[0]]\n'
                '    for current in intervals:\n'
                '        previous = merged[-1]\n'
                '        if current[0] < previous[1]:\n'
                '            previous[1] = max(previous[1], current[1])\n'
                '        else:\n'
                '            merged.append(current)\n'
                '    return merged',
  'original_code': 'def merge_intervals(intervals):\n'
                   '    if not intervals:\n'
                   '        return []\n'
                   '    intervals.sort(key=lambda x: x[0])\n'
                   '    merged = [intervals[0]]\n'
                   '    for current in intervals:\n'
                   '        previous = merged[-1]\n'
                   '        if current[0] <= previous[1]:\n'
                   '            previous[1] = max(previous[1], current[1])\n'
                   '        else:\n'
                   '            merged.append(current)\n'
                   '    return merged',
  'initial_error': 'AssertionError: merge_intervals([[1,4],[4,5]]) expected [[1,5]], got [[1,4],[4,5]]',
  'bug_location': {'function': 'merge_intervals', 'line_start': 8},
  'test_cases': [{'input': [[[1, 3], [2, 6], [8, 10], [15, 18]]], 'expected_output': [[1, 6], [8, 10], [15, 18]]},
                 {'input': [[[1, 4], [4, 5]]], 'expected_output': [[1, 5]]},
                 {'input': [[]], 'expected_output': []},
                 {'input': [[[1, 4], [0, 4]]], 'expected_output': [[0, 4]]}]},
 {'id': 't1_022',
  'difficulty': 1,
  'bug_type': 'logic_inversion',
  'function_name': 'merge_intervals',
  'buggy_code': 'def merge_intervals(intervals):\n'
                '    if intervals:\n'
                '        return []\n'
                '    intervals.sort(key=lambda x: x[0])\n'
                '    merged = [intervals[0]]\n'
                '    for current in intervals:\n'
                '        previous = merged[-1]\n'
                '        if current[0] <= previous[1]:\n'
                '            previous[1] = max(previous[1], current[1])\n'
                '        else:\n'
                '            merged.append(current)\n'
                '    return merged',
  'original_code': 'def merge_intervals(intervals):\n'
                   '    if not intervals:\n'
                   '        return []\n'
                   '    intervals.sort(key=lambda x: x[0])\n'
                   '    merged = [intervals[0]]\n'
                   '    for current in intervals:\n'
                   '        previous = merged[-1]\n'
                   '        if current[0] <= previous[1]:\n'
                   '            previous[1] = max(previous[1], current[1])\n'
                   '        else:\n'
                   '            merged.append(current)\n'
                   '    return merged',
  'initial_error': 'AssertionError: merge_intervals([[1,4],[4,5]]) expected [[1,5]], got []',
  'bug_location': {'function': 'merge_intervals', 'line_start': 2},
  'test_cases': [{'input': [[[1, 3], [2, 6], [8, 10], [15, 18]]], 'expected_output': [[1, 6], [8, 10], [15, 18]]},
                 {'input': [[[1, 4], [4, 5]]], 'expected_output': [[1, 5]]},
                 {'input': [[]], 'expected_output': []},
                 {'input': [[[1, 4], [0, 4]]], 'expected_output': [[0, 4]]}]},
 {'id': 't1_023',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'remove_duplicates',
  'buggy_code': 'def remove_duplicates(nums):\n'
                '    if not nums:\n'
                '        return 0\n'
                '    i = 0\n'
                '    for j in range(1, len(nums)):\n'
                '        if nums[j] == nums[i]:\n'
                '            i += 1\n'
                '            nums[i] = nums[j]\n'
                '    return i + 1',
  'original_code': 'def remove_duplicates(nums):\n'
                   '    if not nums:\n'
                   '        return 0\n'
                   '    i = 0\n'
                   '    for j in range(1, len(nums)):\n'
                   '        if nums[j] != nums[i]:\n'
                   '            i += 1\n'
                   '            nums[i] = nums[j]\n'
                   '    return i + 1',
  'initial_error': 'AssertionError: remove_duplicates([1,1,2]) expected 2, got 2 with array [1,1,2]',
  'bug_location': {'function': 'remove_duplicates', 'line_start': 6},
  'test_cases': [{'input': [[1, 1, 2]], 'expected_output': 2},
                 {'input': [[0, 0, 1, 1, 1, 2, 2, 3, 3, 4]], 'expected_output': 5},
                 {'input': [[]], 'expected_output': 0},
                 {'input': [[1]], 'expected_output': 1}]},
 {'id': 't1_024',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'remove_duplicates',
  'buggy_code': 'def remove_duplicates(nums):\n'
                '    if not nums:\n'
                '        return 0\n'
                '    i = 0\n'
                '    for j in range(1, len(nums)):\n'
                '        if nums[j] != nums[i]:\n'
                '            i += 1\n'
                '            nums[i] = nums[j]\n'
                '    return i',
  'original_code': 'def remove_duplicates(nums):\n'
                   '    if not nums:\n'
                   '        return 0\n'
                   '    i = 0\n'
                   '    for j in range(1, len(nums)):\n'
                   '        if nums[j] != nums[i]:\n'
                   '            i += 1\n'
                   '            nums[i] = nums[j]\n'
                   '    return i + 1',
  'initial_error': 'AssertionError: remove_duplicates([1,1,2]) expected 2, got 1',
  'bug_location': {'function': 'remove_duplicates', 'line_start': 9},
  'test_cases': [{'input': [[1, 1, 2]], 'expected_output': 2},
                 {'input': [[0, 0, 1, 1, 1, 2, 2, 3, 3, 4]], 'expected_output': 5},
                 {'input': [[]], 'expected_output': 0},
                 {'input': [[1]], 'expected_output': 1}]},
 {'id': 't1_025',
  'difficulty': 1,
  'bug_type': 'wrong_comparison',
  'function_name': 'longest_common_prefix',
  'buggy_code': 'def longest_common_prefix(strs):\n'
                '    if not strs:\n'
                '        return ""\n'
                '    prefix = strs[0]\n'
                '    for s in strs[1:]:\n'
                '        while s.startswith(prefix):\n'
                '            prefix = prefix[:-1]\n'
                '            if not prefix:\n'
                '                return ""\n'
                '    return prefix',
  'original_code': 'def longest_common_prefix(strs):\n'
                   '    if not strs:\n'
                   '        return ""\n'
                   '    prefix = strs[0]\n'
                   '    for s in strs[1:]:\n'
                   '        while not s.startswith(prefix):\n'
                   '            prefix = prefix[:-1]\n'
                   '            if not prefix:\n'
                   '                return ""\n'
                   '    return prefix',
  'initial_error': "AssertionError: longest_common_prefix(['flower','flow','flight']) expected 'fl', got ''",
  'bug_location': {'function': 'longest_common_prefix', 'line_start': 6},
  'test_cases': [{'input': [['flower', 'flow', 'flight']], 'expected_output': 'fl'},
                 {'input': [['dog', 'racecar', 'car']], 'expected_output': ''},
                 {'input': [[]], 'expected_output': ''},
                 {'input': [['a']], 'expected_output': 'a'}]},
 {'id': 't1_026',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'longest_common_prefix',
  'buggy_code': 'def longest_common_prefix(strs):\n'
                '    if not strs:\n'
                '        return ""\n'
                '    prefix = strs[0]\n'
                '    for s in strs:\n'
                '        while not s.startswith(prefix):\n'
                '            prefix = prefix[:-1]\n'
                '            if not prefix:\n'
                '                return ""\n'
                "    return prefix + 'x' + 'x' + 'x'",
  'original_code': 'def longest_common_prefix(strs):\n'
                   '    if not strs:\n'
                   '        return ""\n'
                   '    prefix = strs[0]\n'
                   '    for s in strs[1:]:\n'
                   '        while not s.startswith(prefix):\n'
                   '            prefix = prefix[:-1]\n'
                   '            if not prefix:\n'
                   '                return ""\n'
                   '    return prefix',
  'initial_error': "AssertionError: doesn't strictly fail but runs longer",
  'bug_location': {'function': 'longest_common_prefix', 'line_start': 5},
  'test_cases': [{'input': [['flower', 'flow', 'flight']], 'expected_output': 'fl'},
                 {'input': [['dog', 'racecar', 'car']], 'expected_output': ''},
                 {'input': [[]], 'expected_output': ''},
                 {'input': [['a']], 'expected_output': 'a'}]},
 {'id': 't1_027',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'product_except_self',
  'buggy_code': 'def product_except_self(nums):\n'
                '    n = len(nums)\n'
                '    res = [1] * n\n'
                '    prefix = 1\n'
                '    for i in range(n):\n'
                '        res[i] = prefix\n'
                '        prefix += nums[i]\n'
                '    postfix = 1\n'
                '    for i in range(n - 1, -1, -1):\n'
                '        res[i] *= postfix\n'
                '        postfix *= nums[i]\n'
                '    return res',
  'original_code': 'def product_except_self(nums):\n'
                   '    n = len(nums)\n'
                   '    res = [1] * n\n'
                   '    prefix = 1\n'
                   '    for i in range(n):\n'
                   '        res[i] = prefix\n'
                   '        prefix *= nums[i]\n'
                   '    postfix = 1\n'
                   '    for i in range(n - 1, -1, -1):\n'
                   '        res[i] *= postfix\n'
                   '        postfix *= nums[i]\n'
                   '    return res',
  'initial_error': 'AssertionError: product_except_self([1,2,3,4]) expected [24,12,8,6], got [24, 24, 16, 6]',
  'bug_location': {'function': 'product_except_self', 'line_start': 7},
  'test_cases': [{'input': [[1, 2, 3, 4]], 'expected_output': [24, 12, 8, 6]},
                 {'input': [[-1, 1, 0, -3, 3]], 'expected_output': [0, 0, 9, 0, 0]},
                 {'input': [[2, 3]], 'expected_output': [3, 2]},
                 {'input': [[1, 1, 1]], 'expected_output': [1, 1, 1]}]},
 {'id': 't1_028',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'product_except_self',
  'buggy_code': 'def product_except_self(nums):\n'
                '    n = len(nums)\n'
                '    res = [1] * n\n'
                '    prefix = 1\n'
                '    for i in range(n):\n'
                '        res[i] = prefix\n'
                '        prefix *= nums[i]\n'
                '    postfix = 1\n'
                '    for i in range(n - 1, 0, -1):\n'
                '        res[i] *= postfix\n'
                '        postfix *= nums[i]\n'
                '    return res',
  'original_code': 'def product_except_self(nums):\n'
                   '    n = len(nums)\n'
                   '    res = [1] * n\n'
                   '    prefix = 1\n'
                   '    for i in range(n):\n'
                   '        res[i] = prefix\n'
                   '        prefix *= nums[i]\n'
                   '    postfix = 1\n'
                   '    for i in range(n - 1, -1, -1):\n'
                   '        res[i] *= postfix\n'
                   '        postfix *= nums[i]\n'
                   '    return res',
  'initial_error': 'AssertionError: product_except_self([1,2,3,4]) expected [24,12,8,6], got [1,12,8,6]',
  'bug_location': {'function': 'product_except_self', 'line_start': 9},
  'test_cases': [{'input': [[1, 2, 3, 4]], 'expected_output': [24, 12, 8, 6]},
                 {'input': [[-1, 1, 0, -3, 3]], 'expected_output': [0, 0, 9, 0, 0]},
                 {'input': [[2, 3]], 'expected_output': [3, 2]},
                 {'input': [[1, 1, 1]], 'expected_output': [1, 1, 1]}]},
 {'id': 't1_029',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'valid_parentheses',
  'buggy_code': 'def valid_parentheses(s):\n'
                '    stack = []\n'
                "    mapping = {')': '(', '}': '{', ']': '['}\n"
                '    for char in s:\n'
                '        if char in mapping:\n'
                "            top_element = stack.pop() if stack else '#'\n"
                '            if mapping[char] == top_element:\n'
                '                return False\n'
                '        else:\n'
                '            stack.append(char)\n'
                '    return not stack',
  'original_code': 'def valid_parentheses(s):\n'
                   '    stack = []\n'
                   "    mapping = {')': '(', '}': '{', ']': '['}\n"
                   '    for char in s:\n'
                   '        if char in mapping:\n'
                   "            top_element = stack.pop() if stack else '#'\n"
                   '            if mapping[char] != top_element:\n'
                   '                return False\n'
                   '        else:\n'
                   '            stack.append(char)\n'
                   '    return not stack',
  'initial_error': "AssertionError: valid_parentheses('()') expected True, got False",
  'bug_location': {'function': 'valid_parentheses', 'line_start': 7},
  'test_cases': [{'input': ['()'], 'expected_output': True},
                 {'input': ['()[]{}'], 'expected_output': True},
                 {'input': ['(]'], 'expected_output': False},
                 {'input': ['([)]'], 'expected_output': False}]},
 {'id': 't1_030',
  'difficulty': 1,
  'bug_type': 'logic_inversion',
  'function_name': 'valid_parentheses',
  'buggy_code': 'def valid_parentheses(s):\n'
                '    stack = []\n'
                "    mapping = {')': '(', '}': '{', ']': '['}\n"
                '    for char in s:\n'
                '        if char in mapping:\n'
                "            top_element = stack.pop() if stack else '#'\n"
                '            if mapping[char] != top_element:\n'
                '                return False\n'
                '        else:\n'
                '            stack.append(char)\n'
                '    return bool(stack)',
  'original_code': 'def valid_parentheses(s):\n'
                   '    stack = []\n'
                   "    mapping = {')': '(', '}': '{', ']': '['}\n"
                   '    for char in s:\n'
                   '        if char in mapping:\n'
                   "            top_element = stack.pop() if stack else '#'\n"
                   '            if mapping[char] != top_element:\n'
                   '                return False\n'
                   '        else:\n'
                   '            stack.append(char)\n'
                   '    return not stack',
  'initial_error': "AssertionError: valid_parentheses('()') expected True, got False",
  'bug_location': {'function': 'valid_parentheses', 'line_start': 11},
  'test_cases': [{'input': ['()'], 'expected_output': True},
                 {'input': ['()[]{}'], 'expected_output': True},
                 {'input': ['(]'], 'expected_output': False},
                 {'input': ['([)]'], 'expected_output': False}]},
 {'id': 't1_031',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'climbing_stairs',
  'buggy_code': 'def climbing_stairs(n):\n'
                '    if n <= 2:\n'
                '        return n\n'
                '    a, b = 1, 2\n'
                '    for _ in range(3, n):\n'
                '        a, b = b, a + b\n'
                '    return b',
  'original_code': 'def climbing_stairs(n):\n'
                   '    if n <= 2:\n'
                   '        return n\n'
                   '    a, b = 1, 2\n'
                   '    for _ in range(3, n + 1):\n'
                   '        a, b = b, a + b\n'
                   '    return b',
  'initial_error': 'AssertionError: climbing_stairs(3) expected 3, got 2',
  'bug_location': {'function': 'climbing_stairs', 'line_start': 5},
  'test_cases': [{'input': [2], 'expected_output': 2},
                 {'input': [3], 'expected_output': 3},
                 {'input': [1], 'expected_output': 1},
                 {'input': [5], 'expected_output': 8}]},
 {'id': 't1_032',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'climbing_stairs',
  'buggy_code': 'def climbing_stairs(n):\n'
                '    if n <= 2:\n'
                '        return n\n'
                '    a, b = 1, 2\n'
                '    for _ in range(3, n + 1):\n'
                '        a, b = b, a * b\n'
                '    return b',
  'original_code': 'def climbing_stairs(n):\n'
                   '    if n <= 2:\n'
                   '        return n\n'
                   '    a, b = 1, 2\n'
                   '    for _ in range(3, n + 1):\n'
                   '        a, b = b, a + b\n'
                   '    return b',
  'initial_error': 'AssertionError: climbing_stairs(3) expected 3, got 2',
  'bug_location': {'function': 'climbing_stairs', 'line_start': 6},
  'test_cases': [{'input': [2], 'expected_output': 2},
                 {'input': [3], 'expected_output': 3},
                 {'input': [1], 'expected_output': 1},
                 {'input': [5], 'expected_output': 8}]},
 {'id': 't1_033',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'house_robber',
  'buggy_code': 'def house_robber(nums):\n'
                '    if not nums:\n'
                '        return 0\n'
                '    if len(nums) == 1:\n'
                '        return nums[0]\n'
                '    dp = [0] * len(nums)\n'
                '    dp[0] = nums[0]\n'
                '    dp[1] = 9999\n'
                '    for i in range(2, len(nums)):\n'
                '        dp[i] = max(dp[i-1], dp[i-2] + nums[i])\n'
                '    return dp[-1]',
  'original_code': 'def house_robber(nums):\n'
                   '    if not nums:\n'
                   '        return 0\n'
                   '    if len(nums) == 1:\n'
                   '        return nums[0]\n'
                   '    dp = [0] * len(nums)\n'
                   '    dp[0] = nums[0]\n'
                   '    dp[1] = max(nums[0], nums[1])\n'
                   '    for i in range(2, len(nums)):\n'
                   '        dp[i] = max(dp[i-1], dp[i-2] + nums[i])\n'
                   '    return dp[-1]',
  'initial_error': 'AssertionError: house_robber([2,7,9,3,1]) expected 12, got 11',
  'bug_location': {'function': 'house_robber', 'line_start': 8},
  'test_cases': [{'input': [[1, 2, 3, 1]], 'expected_output': 4},
                 {'input': [[2, 7, 9, 3, 1]], 'expected_output': 12},
                 {'input': [[]], 'expected_output': 0},
                 {'input': [[5]], 'expected_output': 5}]},
 {'id': 't1_034',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'house_robber',
  'buggy_code': 'def house_robber(nums):\n'
                '    if not nums:\n'
                '        return 0\n'
                '    if len(nums) == 1:\n'
                '        return nums[0]\n'
                '    dp = [0] * len(nums)\n'
                '    dp[0] = nums[0]\n'
                '    dp[1] = max(nums[0], nums[1])\n'
                '    for i in range(1, len(nums)):\n'
                '        dp[i] = max(dp[i-1], nums[i])\n'
                '    return dp[-1]',
  'original_code': 'def house_robber(nums):\n'
                   '    if not nums:\n'
                   '        return 0\n'
                   '    if len(nums) == 1:\n'
                   '        return nums[0]\n'
                   '    dp = [0] * len(nums)\n'
                   '    dp[0] = nums[0]\n'
                   '    dp[1] = max(nums[0], nums[1])\n'
                   '    for i in range(2, len(nums)):\n'
                   '        dp[i] = max(dp[i-1], dp[i-2] + nums[i])\n'
                   '    return dp[-1]',
  'initial_error': 'IndexError: list index out of range',
  'bug_location': {'function': 'house_robber', 'line_start': 9},
  'test_cases': [{'input': [[1, 2, 3, 1]], 'expected_output': 4},
                 {'input': [[2, 7, 9, 3, 1]], 'expected_output': 12},
                 {'input': [[]], 'expected_output': 0},
                 {'input': [[5]], 'expected_output': 5}]},
 {'id': 't1_035',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'intersection_of_arrays',
  'buggy_code': 'def intersection_of_arrays(nums1, nums2):\n    return list(set(nums1) | set(nums2))',
  'original_code': 'def intersection_of_arrays(nums1, nums2):\n    return list(set(nums1) & set(nums2))',
  'initial_error': 'AssertionError: intersection_of_arrays([1,2,2,1], [2,2]) expected [2], got [1,2]',
  'bug_location': {'function': 'intersection_of_arrays', 'line_start': 2},
  'test_cases': [{'input': [[1, 2, 2, 1], [2, 2]], 'expected_output': [2]},
                 {'input': [[4, 9, 5], [9, 4, 9, 8, 4]], 'expected_output': [9, 4]},
                 {'input': [[], [1]], 'expected_output': []},
                 {'input': [[1, 2], [3, 4]], 'expected_output': []}]},
 {'id': 't1_036',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'intersection_of_arrays',
  'buggy_code': 'def intersection_of_arrays(nums1, nums2):\n    return list(set(nums1) - set(nums2))',
  'original_code': 'def intersection_of_arrays(nums1, nums2):\n    return list(set(nums1) & set(nums2))',
  'initial_error': 'AssertionError: intersection_of_arrays([1,2,2,1], [2,2]) expected [2], got [1]',
  'bug_location': {'function': 'intersection_of_arrays', 'line_start': 2},
  'test_cases': [{'input': [[1, 2, 2, 1], [2, 2]], 'expected_output': [2]},
                 {'input': [[4, 9, 5], [9, 4, 9, 8, 4]], 'expected_output': [9, 4]},
                 {'input': [[], [1]], 'expected_output': []},
                 {'input': [[1, 2], [3, 4]], 'expected_output': []}]},
 {'id': 't1_037',
  'difficulty': 1,
  'bug_type': 'wrong_comparison',
  'function_name': 'group_anagrams',
  'buggy_code': 'def group_anagrams(strs):\n'
                '    from collections import defaultdict\n'
                '    ans = defaultdict(list)\n'
                '    for s in strs:\n'
                '        ans[tuple(s)].append(s)\n'
                '    return list(ans.values())',
  'original_code': 'def group_anagrams(strs):\n'
                   '    from collections import defaultdict\n'
                   '    ans = defaultdict(list)\n'
                   '    for s in strs:\n'
                   '        ans[tuple(sorted(s))].append(s)\n'
                   '    return list(ans.values())',
  'initial_error': "AssertionError: expected [['eat','tea','ate'],['tan','nat'],['bat']]",
  'bug_location': {'function': 'group_anagrams', 'line_start': 5},
  'test_cases': [{'input': [['eat', 'tea', 'tan', 'ate', 'nat', 'bat']],
                  'expected_output': [['eat', 'tea', 'ate'], ['tan', 'nat'], ['bat']]},
                 {'input': [['']], 'expected_output': [['']]},
                 {'input': [['a']], 'expected_output': [['a']]},
                 {'input': [['ab', 'ba']], 'expected_output': [['ab', 'ba']]}]},
 {'id': 't1_038',
  'difficulty': 1,
  'bug_type': 'logic_inversion',
  'function_name': 'group_anagrams',
  'buggy_code': 'def group_anagrams(strs):\n'
                '    from collections import defaultdict\n'
                '    ans = defaultdict(list)\n'
                '    for s in strs:\n'
                '        ans[tuple(sorted(s))].append(s[::-1])\n'
                '    return list(ans.values())',
  'original_code': 'def group_anagrams(strs):\n'
                   '    from collections import defaultdict\n'
                   '    ans = defaultdict(list)\n'
                   '    for s in strs:\n'
                   '        ans[tuple(sorted(s))].append(s)\n'
                   '    return list(ans.values())',
  'initial_error': "AssertionError: expected [['eat','tea','ate'],['tan','nat'],['bat']]",
  'bug_location': {'function': 'group_anagrams', 'line_start': 5},
  'test_cases': [{'input': [['eat', 'tea', 'tan', 'ate', 'nat', 'bat']],
                  'expected_output': [['eat', 'tea', 'ate'], ['tan', 'nat'], ['bat']]},
                 {'input': [['']], 'expected_output': [['']]},
                 {'input': [['a']], 'expected_output': [['a']]},
                 {'input': [['ab', 'ba']], 'expected_output': [['ab', 'ba']]}]},
 {'id': 't1_039',
  'difficulty': 1,
  'bug_type': 'wrong_operator',
  'function_name': 'sum_digits',
  'buggy_code': 'def sum_digits(n):\n'
                '    total = 0\n'
                '    while n > 0:\n'
                '        total *= n % 10\n'
                '        n //= 10\n'
                '    return total',
  'original_code': 'def sum_digits(n):\n'
                   '    total = 0\n'
                   '    while n > 0:\n'
                   '        total += n % 10\n'
                   '        n //= 10\n'
                   '    return total',
  'initial_error': 'AssertionError: sum_digits(123) expected 6, got 0',
  'bug_location': {'function': 'sum_digits', 'line_start': 4},
  'test_cases': [{'input': [123], 'expected_output': 6},
                 {'input': [0], 'expected_output': 0},
                 {'input': [999], 'expected_output': 27},
                 {'input': [10], 'expected_output': 1}]},
 {'id': 't1_040',
  'difficulty': 1,
  'bug_type': 'off_by_one',
  'function_name': 'factorial',
  'buggy_code': 'def factorial(n):\n    if n <= 0:\n        return 0\n    return n * factorial(n - 1)',
  'original_code': 'def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n - 1)',
  'initial_error': 'AssertionError: factorial(3) expected 6, got 0',
  'bug_location': {'function': 'factorial', 'line_start': 3},
  'test_cases': [{'input': [0], 'expected_output': 1},
                 {'input': [1], 'expected_output': 1},
                 {'input': [5], 'expected_output': 120},
                 {'input': [3], 'expected_output': 6}]}]

TIER2_BUGS = [{'id': 't2_001',
  'difficulty': 2,
  'bug_type': 'wrong_variable',
  'function_name': 'two_sum',
  'buggy_code': 'def two_sum(nums, target):\n'
                '    seen = {}\n'
                '    for i, num in enumerate(nums):\n'
                '        complement = target - num\n'
                '        if complement in seen:\n'
                '            return [seen[complement], i]\n'
                '        seen[num] = num\n'
                '    return []',
  'original_code': 'def two_sum(nums, target):\n'
                   '    seen = {}\n'
                   '    for i, num in enumerate(nums):\n'
                   '        complement = target - num\n'
                   '        if complement in seen:\n'
                   '            return [seen[complement], i]\n'
                   '        seen[num] = i\n'
                   '    return []',
  'initial_error': 'AssertionError: two_sum([2,7,11,15], 9) expected [0,1], got [2,1]',
  'bug_location': {'function': 'two_sum', 'line_start': 7},
  'test_cases': [{'input': [[2, 7, 11, 15], 9], 'expected_output': [0, 1]},
                 {'input': [[3, 2, 4], 6], 'expected_output': [1, 2]},
                 {'input': [[3, 3], 6], 'expected_output': [0, 1]}]},
 {'id': 't2_002',
  'difficulty': 2,
  'bug_type': 'missing_base_case',
  'function_name': 'fibonacci',
  'buggy_code': 'def fibonacci(n):\n    if n == 0:\n        return 0\n    return fibonacci(n - 1) + fibonacci(n - 2)',
  'original_code': 'def fibonacci(n):\n'
                   '    if n == 0:\n'
                   '        return 0\n'
                   '    if n == 1:\n'
                   '        return 1\n'
                   '    return fibonacci(n - 1) + fibonacci(n - 2)',
  'initial_error': 'RecursionError: maximum recursion depth exceeded',
  'bug_location': {'function': 'fibonacci', 'line_start': 4},
  'test_cases': [{'input': [0], 'expected_output': 0},
                 {'input': [1], 'expected_output': 1},
                 {'input': [5], 'expected_output': 5},
                 {'input': [7], 'expected_output': 13}]},
 {'id': 't2_003',
  'difficulty': 2,
  'bug_type': 'wrong_accumulator',
  'function_name': 'flatten',
  'buggy_code': 'def flatten(lst):\n'
                '    result = []\n'
                '    for item in lst:\n'
                '        if isinstance(item, list):\n'
                '            result.append(flatten(item))\n'
                '        else:\n'
                '            result.append(item)\n'
                '    return result',
  'original_code': 'def flatten(lst):\n'
                   '    result = []\n'
                   '    for item in lst:\n'
                   '        if isinstance(item, list):\n'
                   '            result.extend(flatten(item))\n'
                   '        else:\n'
                   '            result.append(item)\n'
                   '    return result',
  'initial_error': 'AssertionError: flatten([[1,[2]],3]) expected [1,2,3], got [1,[2],3]',
  'bug_location': {'function': 'flatten', 'line_start': 5},
  'test_cases': [{'input': [[[1, [2]], 3]], 'expected_output': [1, 2, 3]},
                 {'input': [[1, 2, 3]], 'expected_output': [1, 2, 3]},
                 {'input': [[[1, 2], [3, [4, 5]]]], 'expected_output': [1, 2, 3, 4, 5]}]},
 {'id': 't2_004',
  'difficulty': 2,
  'bug_type': 'wrong_loop_termination',
  'function_name': 'find_first_positive',
  'buggy_code': 'def find_first_positive(nums):\n'
                '    i = 0\n'
                '    while i < len(nums) - 1:\n'
                '        if nums[i] > 0:\n'
                '            return nums[i]\n'
                '        i += 1\n'
                '    return -1',
  'original_code': 'def find_first_positive(nums):\n'
                   '    i = 0\n'
                   '    while i < len(nums):\n'
                   '        if nums[i] > 0:\n'
                   '            return nums[i]\n'
                   '        i += 1\n'
                   '    return -1',
  'initial_error': 'AssertionError: expected 5, got -1',
  'bug_location': {'function': 'find_first_positive', 'line_start': 3},
  'test_cases': [{'input': [[-1, -2, 5]], 'expected_output': 5},
                 {'input': [[1, 2, 3]], 'expected_output': 1},
                 {'input': [[-1]], 'expected_output': -1},
                 {'input': [[-5, -3, -1, 10]], 'expected_output': 10}]},
 {'id': 't2_005',
  'difficulty': 2,
  'bug_type': 'wrong_loop_termination',
  'function_name': 'binary_search_insert',
  'buggy_code': 'def binary_search_insert(arr, target):\n'
                '    left, right = 0, len(arr) - 1\n'
                '    while left < right:\n'
                '        mid = (left + right) // 2\n'
                '        if arr[mid] < target:\n'
                '            left = mid + 1\n'
                '        else:\n'
                '            right = mid\n'
                '    return left',
  'original_code': 'def binary_search_insert(arr, target):\n'
                   '    left, right = 0, len(arr)\n'
                   '    while left < right:\n'
                   '        mid = (left + right) // 2\n'
                   '        if arr[mid] < target:\n'
                   '            left = mid + 1\n'
                   '        else:\n'
                   '            right = mid\n'
                   '    return left',
  'initial_error': 'AssertionError: expected 3, got 2',
  'bug_location': {'function': 'binary_search_insert', 'line_start': 2},
  'test_cases': [{'input': [[1, 3, 5], 6], 'expected_output': 3},
                 {'input': [[1, 3, 5], 4], 'expected_output': 2},
                 {'input': [[1, 3, 5], 0], 'expected_output': 0},
                 {'input': [[], 1], 'expected_output': 0}]},
 {'id': 't2_006',
  'difficulty': 2,
  'bug_type': 'wrong_loop_termination',
  'function_name': 'countdown_to_zero',
  'buggy_code': 'def countdown_to_zero(n):\n'
                '    res = []\n'
                '    while n > 0:\n'
                '        res.append(n)\n'
                '        n -= 1\n'
                '    return res',
  'original_code': 'def countdown_to_zero(n):\n'
                   '    res = []\n'
                   '    while n >= 0:\n'
                   '        res.append(n)\n'
                   '        n -= 1\n'
                   '    return res',
  'initial_error': 'AssertionError: expected [3, 2, 1, 0], got [3, 2, 1]',
  'bug_location': {'function': 'countdown_to_zero', 'line_start': 3},
  'test_cases': [{'input': [3], 'expected_output': [3, 2, 1, 0]},
                 {'input': [0], 'expected_output': [0]},
                 {'input': [1], 'expected_output': [1, 0]},
                 {'input': [-1], 'expected_output': []}]},
 {'id': 't2_007',
  'difficulty': 2,
  'bug_type': 'wrong_loop_termination',
  'function_name': 'collect_until_negative',
  'buggy_code': 'def collect_until_negative(nums):\n'
                '    res = []\n'
                '    i = 0\n'
                '    while i <= len(nums) and nums[i] >= 0:\n'
                '        res.append(nums[i])\n'
                '        i += 1\n'
                '    return res',
  'original_code': 'def collect_until_negative(nums):\n'
                   '    res = []\n'
                   '    i = 0\n'
                   '    while i < len(nums) and nums[i] >= 0:\n'
                   '        res.append(nums[i])\n'
                   '        i += 1\n'
                   '    return res',
  'initial_error': 'IndexError: list index out of range',
  'bug_location': {'function': 'collect_until_negative', 'line_start': 4},
  'test_cases': [{'input': [[1, 2, -1, 3]], 'expected_output': [1, 2]},
                 {'input': [[1, 2, 3]], 'expected_output': [1, 2, 3]},
                 {'input': [[-1]], 'expected_output': []},
                 {'input': [[]], 'expected_output': []}]},
 {'id': 't2_008',
  'difficulty': 2,
  'bug_type': 'wrong_loop_termination',
  'function_name': 'skip_spaces',
  'buggy_code': "def skip_spaces(s):\n    i = 0\n    while s[i] == ' ':\n        i += 1\n    return s[i:]",
  'original_code': 'def skip_spaces(s):\n'
                   '    i = 0\n'
                   "    while i < len(s) and s[i] == ' ':\n"
                   '        i += 1\n'
                   '    return s[i:]',
  'initial_error': 'IndexError: string index out of range',
  'bug_location': {'function': 'skip_spaces', 'line_start': 3},
  'test_cases': [{'input': ['  hello'], 'expected_output': 'hello'},
                 {'input': ['   '], 'expected_output': ''},
                 {'input': ['world'], 'expected_output': 'world'},
                 {'input': [''], 'expected_output': ''}]},
 {'id': 't2_009',
  'difficulty': 2,
  'bug_type': 'wrong_loop_termination',
  'function_name': 'find_last_even',
  'buggy_code': 'def find_last_even(nums):\n'
                '    i = len(nums) - 1\n'
                '    while i > 0:\n'
                '        if nums[i] % 2 == 0:\n'
                '            return nums[i]\n'
                '        i -= 1\n'
                '    return -1',
  'original_code': 'def find_last_even(nums):\n'
                   '    i = len(nums) - 1\n'
                   '    while i >= 0:\n'
                   '        if nums[i] % 2 == 0:\n'
                   '            return nums[i]\n'
                   '        i -= 1\n'
                   '    return -1',
  'initial_error': 'AssertionError: expected 2, got -1',
  'bug_location': {'function': 'find_last_even', 'line_start': 3},
  'test_cases': [{'input': [[2, 3, 5]], 'expected_output': 2},
                 {'input': [[1, 3, 4]], 'expected_output': 4},
                 {'input': [[1, 3, 5]], 'expected_output': -1},
                 {'input': [[6]], 'expected_output': 6}]},
 {'id': 't2_010',
  'difficulty': 2,
  'bug_type': 'wrong_loop_termination',
  'function_name': 'get_chunks',
  'buggy_code': 'def get_chunks(lst, size):\n'
                '    chunks = []\n'
                '    i = 0\n'
                '    while i < len(lst) - size:\n'
                '        chunks.append(lst[i:i+size])\n'
                '        i += size\n'
                '    return chunks',
  'original_code': 'def get_chunks(lst, size):\n'
                   '    chunks = []\n'
                   '    i = 0\n'
                   '    while i < len(lst):\n'
                   '        chunks.append(lst[i:i+size])\n'
                   '        i += size\n'
                   '    return chunks',
  'initial_error': 'AssertionError: expected [[1,2],[3]], got [[1,2]]',
  'bug_location': {'function': 'get_chunks', 'line_start': 4},
  'test_cases': [{'input': [[1, 2, 3], 2], 'expected_output': [[1, 2], [3]]},
                 {'input': [[1, 2], 2], 'expected_output': [[1, 2]]},
                 {'input': [[1, 2, 3, 4], 2], 'expected_output': [[1, 2], [3, 4]]},
                 {'input': [[], 2], 'expected_output': []}]},
 {'id': 't2_011',
  'difficulty': 2,
  'bug_type': 'incorrect_accumulation',
  'function_name': 'sum_even_numbers',
  'buggy_code': 'def sum_even_numbers(nums):\n'
                '    total = 1\n'
                '    for n in nums:\n'
                '        if n % 2 == 0:\n'
                '            total += n\n'
                '    return total',
  'original_code': 'def sum_even_numbers(nums):\n'
                   '    total = 0\n'
                   '    for n in nums:\n'
                   '        if n % 2 == 0:\n'
                   '            total += n\n'
                   '    return total',
  'initial_error': 'AssertionError: expected 6, got 7',
  'bug_location': {'function': 'sum_even_numbers', 'line_start': 2},
  'test_cases': [{'input': [[1, 2, 3, 4]], 'expected_output': 6},
                 {'input': [[1, 3, 5]], 'expected_output': 0},
                 {'input': [[2, 2]], 'expected_output': 4},
                 {'input': [[]], 'expected_output': 0}]},
 {'id': 't2_012',
  'difficulty': 2,
  'bug_type': 'incorrect_accumulation',
  'function_name': 'multiply_all',
  'buggy_code': 'def multiply_all(nums):\n    total = 0\n    for n in nums:\n        total *= n\n    return total',
  'original_code': 'def multiply_all(nums):\n    total = 1\n    for n in nums:\n        total *= n\n    return total',
  'initial_error': 'AssertionError: expected 24, got 0',
  'bug_location': {'function': 'multiply_all', 'line_start': 2},
  'test_cases': [{'input': [[1, 2, 3, 4]], 'expected_output': 24},
                 {'input': [[5]], 'expected_output': 5},
                 {'input': [[1, -1]], 'expected_output': -1},
                 {'input': [[0, 5]], 'expected_output': 0}]},
 {'id': 't2_013',
  'difficulty': 2,
  'bug_type': 'incorrect_accumulation',
  'function_name': 'concatenate_strings',
  'buggy_code': 'def concatenate_strings(strs):\n'
                '    res = strs[0]\n'
                '    for s in strs:\n'
                '        res += s\n'
                '    return res',
  'original_code': "def concatenate_strings(strs):\n    res = ''\n    for s in strs:\n        res += s\n    return res",
  'initial_error': "AssertionError: expected 'abc', got 'aabc'",
  'bug_location': {'function': 'concatenate_strings', 'line_start': 2},
  'test_cases': [{'input': [['a', 'b', 'c']], 'expected_output': 'abc'},
                 {'input': [['hello', 'world']], 'expected_output': 'helloworld'},
                 {'input': [['a']], 'expected_output': 'a'},
                 {'input': [['x', 'y']], 'expected_output': 'xy'}]},
 {'id': 't2_014',
  'difficulty': 2,
  'bug_type': 'incorrect_accumulation',
  'function_name': 'max_profit',
  'buggy_code': 'def max_profit(prices):\n'
                '    min_price = 0\n'
                '    max_prof = 0\n'
                '    for price in prices:\n'
                '        min_price = min(min_price, price)\n'
                '        max_prof = max(max_prof, price - min_price)\n'
                '    return max_prof',
  'original_code': 'def max_profit(prices):\n'
                   "    min_price = float('inf')\n"
                   '    max_prof = 0\n'
                   '    for price in prices:\n'
                   '        min_price = min(min_price, price)\n'
                   '        max_prof = max(max_prof, price - min_price)\n'
                   '    return max_prof',
  'initial_error': 'AssertionError: expected 5, got 6',
  'bug_location': {'function': 'max_profit', 'line_start': 2},
  'test_cases': [{'input': [[7, 1, 5, 3, 6, 4]], 'expected_output': 5},
                 {'input': [[7, 6, 4, 3, 1]], 'expected_output': 0},
                 {'input': [[1, 2]], 'expected_output': 1},
                 {'input': [[2, 4, 1]], 'expected_output': 2}]},
 {'id': 't2_015',
  'difficulty': 2,
  'bug_type': 'incorrect_accumulation',
  'function_name': 'find_longest_word',
  'buggy_code': 'def find_longest_word(words):\n'
                '    longest = words[0]\n'
                '    for word in words:\n'
                '        if len(word) > len(longest):\n'
                '            longest = longest\n'
                '    return longest',
  'original_code': 'def find_longest_word(words):\n'
                   "    longest = ''\n"
                   '    for word in words:\n'
                   '        if len(word) > len(longest):\n'
                   '            longest = word\n'
                   '    return longest',
  'initial_error': "AssertionError: expected 'banana', got 'apple'",
  'bug_location': {'function': 'find_longest_word', 'line_start': 5},
  'test_cases': [{'input': [['apple', 'banana', 'kiwi']], 'expected_output': 'banana'},
                 {'input': [['a', 'ab', 'abc']], 'expected_output': 'abc'},
                 {'input': [['dog']], 'expected_output': 'dog'},
                 {'input': [['x', 'yz']], 'expected_output': 'yz'}]},
 {'id': 't2_016',
  'difficulty': 2,
  'bug_type': 'incorrect_accumulation',
  'function_name': 'running_sum',
  'buggy_code': 'def running_sum(nums):\n'
                '    res = []\n'
                '    current = nums[0]\n'
                '    for n in nums:\n'
                '        current += n\n'
                '        res.append(current)\n'
                '    return res',
  'original_code': 'def running_sum(nums):\n'
                   '    res = []\n'
                   '    current = 0\n'
                   '    for n in nums:\n'
                   '        current += n\n'
                   '        res.append(current)\n'
                   '    return res',
  'initial_error': 'AssertionError: expected [1, 3, 6], got [2, 4, 7]',
  'bug_location': {'function': 'running_sum', 'line_start': 3},
  'test_cases': [{'input': [[1, 2, 3]], 'expected_output': [1, 3, 6]},
                 {'input': [[1, 1, 1]], 'expected_output': [1, 2, 3]},
                 {'input': [[5]], 'expected_output': [5]},
                 {'input': [[0, 0, 0]], 'expected_output': [0, 0, 0]}]},
 {'id': 't2_017',
  'difficulty': 2,
  'bug_type': 'incorrect_accumulation',
  'function_name': 'count_negatives',
  'buggy_code': 'def count_negatives(nums):\n'
                '    count = -1\n'
                '    for n in nums:\n'
                '        if n < 0:\n'
                '            count += 1\n'
                '    return count',
  'original_code': 'def count_negatives(nums):\n'
                   '    count = 0\n'
                   '    for n in nums:\n'
                   '        if n < 0:\n'
                   '            count += 1\n'
                   '    return count',
  'initial_error': 'AssertionError: expected 2, got 1',
  'bug_location': {'function': 'count_negatives', 'line_start': 2},
  'test_cases': [{'input': [[1, -1, 2, -2]], 'expected_output': 2},
                 {'input': [[1, 2, 3]], 'expected_output': 0},
                 {'input': [[-1, -2, -3]], 'expected_output': 3},
                 {'input': [[]], 'expected_output': 0}]},
 {'id': 't2_018',
  'difficulty': 2,
  'bug_type': 'wrong_conditional_branch',
  'function_name': 'classify_number',
  'buggy_code': 'def classify_number(n):\n'
                '    if n > 0:\n'
                "        return 'positive'\n"
                '    elif n < 0:\n'
                "        return 'negative'\n"
                '    elif n == 0:\n'
                "        return 'negative'",
  'original_code': 'def classify_number(n):\n'
                   '    if n > 0:\n'
                   "        return 'positive'\n"
                   '    elif n < 0:\n'
                   "        return 'negative'\n"
                   '    else:\n'
                   "        return 'zero'",
  'initial_error': "AssertionError: expected 'zero', got 'negative'",
  'bug_location': {'function': 'classify_number', 'line_start': 6},
  'test_cases': [{'input': [5], 'expected_output': 'positive'},
                 {'input': [-3], 'expected_output': 'negative'},
                 {'input': [0], 'expected_output': 'zero'},
                 {'input': [1], 'expected_output': 'positive'}]},
 {'id': 't2_019',
  'difficulty': 2,
  'bug_type': 'wrong_conditional_branch',
  'function_name': 'get_discount',
  'buggy_code': 'def get_discount(price):\n'
                '    if price > 100:\n'
                '        return 20\n'
                '    if price > 50:\n'
                '        return 50\n'
                '    return 0',
  'original_code': 'def get_discount(price):\n'
                   '    if price > 100:\n'
                   '        return 20\n'
                   '    elif price > 50:\n'
                   '        return 10\n'
                   '    return 0',
  'initial_error': 'AssertionError: expected 10, got 50',
  'bug_location': {'function': 'get_discount', 'line_start': 5},
  'test_cases': [{'input': [150], 'expected_output': 20},
                 {'input': [75], 'expected_output': 10},
                 {'input': [50], 'expected_output': 0},
                 {'input': [20], 'expected_output': 0}]},
 {'id': 't2_020',
  'difficulty': 2,
  'bug_type': 'wrong_conditional_branch',
  'function_name': 'fizz_buzz',
  'buggy_code': 'def fizz_buzz(n):\n'
                '    if n % 3 == 0:\n'
                "        return 'Fizz'\n"
                '    if n % 5 == 0:\n'
                "        return 'Buzz'\n"
                '    if n % 15 == 0:\n'
                "        return 'FizzBuzz'\n"
                '    return str(n)',
  'original_code': 'def fizz_buzz(n):\n'
                   '    if n % 15 == 0:\n'
                   "        return 'FizzBuzz'\n"
                   '    if n % 3 == 0:\n'
                   "        return 'Fizz'\n"
                   '    if n % 5 == 0:\n'
                   "        return 'Buzz'\n"
                   '    return str(n)',
  'initial_error': "AssertionError: expected 'FizzBuzz', got 'Fizz'",
  'bug_location': {'function': 'fizz_buzz', 'line_start': 2},
  'test_cases': [{'input': [3], 'expected_output': 'Fizz'},
                 {'input': [5], 'expected_output': 'Buzz'},
                 {'input': [15], 'expected_output': 'FizzBuzz'},
                 {'input': [2], 'expected_output': '2'}]},
 {'id': 't2_021',
  'difficulty': 2,
  'bug_type': 'wrong_conditional_branch',
  'function_name': 'is_leap_year',
  'buggy_code': 'def is_leap_year(year):\n'
                '    if year % 4 == 0:\n'
                '        if year % 100 == 0:\n'
                '            if year % 400 == 0:\n'
                '                return False\n'
                '            return True\n'
                '        return True\n'
                '    return False',
  'original_code': 'def is_leap_year(year):\n'
                   '    if year % 4 == 0:\n'
                   '        if year % 100 == 0:\n'
                   '            if year % 400 == 0:\n'
                   '                return True\n'
                   '            return False\n'
                   '        return True\n'
                   '    return False',
  'initial_error': 'AssertionError: expected False, got True',
  'bug_location': {'function': 'is_leap_year', 'line_start': 5},
  'test_cases': [{'input': [2000], 'expected_output': True},
                 {'input': [1900], 'expected_output': False},
                 {'input': [2004], 'expected_output': True},
                 {'input': [2001], 'expected_output': False}]},
 {'id': 't2_022',
  'difficulty': 2,
  'bug_type': 'wrong_conditional_branch',
  'function_name': 'grade_score',
  'buggy_code': 'def grade_score(score):\n'
                '    if score >= 90:\n'
                "        return 'A'\n"
                '    elif score >= 80:\n'
                "        return 'B'\n"
                '    elif score > 70:\n'
                "        return 'C'\n"
                '    else:\n'
                "        return 'F'",
  'original_code': 'def grade_score(score):\n'
                   '    if score >= 90:\n'
                   "        return 'A'\n"
                   '    elif score >= 80:\n'
                   "        return 'B'\n"
                   '    elif score >= 70:\n'
                   "        return 'C'\n"
                   '    else:\n'
                   "        return 'F'",
  'initial_error': "AssertionError: expected 'C', got 'F'",
  'bug_location': {'function': 'grade_score', 'line_start': 6},
  'test_cases': [{'input': [95], 'expected_output': 'A'},
                 {'input': [80], 'expected_output': 'B'},
                 {'input': [70], 'expected_output': 'C'},
                 {'input': [60], 'expected_output': 'F'}]},
 {'id': 't2_023',
  'difficulty': 2,
  'bug_type': 'wrong_conditional_branch',
  'function_name': 'can_drink_alcohol',
  'buggy_code': 'def can_drink_alcohol(age, country):\n'
                "    if country == 'US':\n"
                '        if age > 21:\n'
                '            return True\n'
                '        return False\n'
                '    return age >= 18',
  'original_code': 'def can_drink_alcohol(age, country):\n'
                   "    if country == 'US':\n"
                   '        if age >= 21:\n'
                   '            return True\n'
                   '        return False\n'
                   '    return age >= 18',
  'initial_error': 'AssertionError: expected True, got False',
  'bug_location': {'function': 'can_drink_alcohol', 'line_start': 3},
  'test_cases': [{'input': [21, 'US'], 'expected_output': True},
                 {'input': [20, 'US'], 'expected_output': False},
                 {'input': [18, 'UK'], 'expected_output': True},
                 {'input': [17, 'UK'], 'expected_output': False}]},
 {'id': 't2_024',
  'difficulty': 2,
  'bug_type': 'wrong_conditional_branch',
  'function_name': 'get_quadrant',
  'buggy_code': 'def get_quadrant(x, y):\n'
                '    if x > 0 and y > 0:\n'
                '        return 1\n'
                '    elif x < 0 and y > 0:\n'
                '        return 2\n'
                '    elif x > 0 and y < 0:\n'
                '        return 3\n'
                '    elif x < 0 and y < 0:\n'
                '        return 4\n'
                '    return 0',
  'original_code': 'def get_quadrant(x, y):\n'
                   '    if x > 0 and y > 0:\n'
                   '        return 1\n'
                   '    elif x < 0 and y > 0:\n'
                   '        return 2\n'
                   '    elif x < 0 and y < 0:\n'
                   '        return 3\n'
                   '    elif x > 0 and y < 0:\n'
                   '        return 4\n'
                   '    return 0',
  'initial_error': 'AssertionError: expected 4, got 3',
  'bug_location': {'function': 'get_quadrant', 'line_start': 6},
  'test_cases': [{'input': [1, 1], 'expected_output': 1},
                 {'input': [-1, 1], 'expected_output': 2},
                 {'input': [-1, -1], 'expected_output': 3},
                 {'input': [1, -1], 'expected_output': 4}]},
 {'id': 't2_025',
  'difficulty': 2,
  'bug_type': 'wrong_variable',
  'function_name': 'merge_arrays',
  'buggy_code': 'def merge_arrays(a, b):\n    res = a + b\n    res.sort()\n    return a',
  'original_code': 'def merge_arrays(a, b):\n    res = a + b\n    res.sort()\n    return res',
  'initial_error': 'AssertionError: expected [1, 2, 3, 4], got [1, 3]',
  'bug_location': {'function': 'merge_arrays', 'line_start': 4},
  'test_cases': [{'input': [[1, 3], [2, 4]], 'expected_output': [1, 2, 3, 4]},
                 {'input': [[], [1]], 'expected_output': [1]},
                 {'input': [[2], [1]], 'expected_output': [1, 2]},
                 {'input': [[], []], 'expected_output': []}]},
 {'id': 't2_026',
  'difficulty': 2,
  'bug_type': 'wrong_variable',
  'function_name': 'find_min_max',
  'buggy_code': 'def find_min_max(nums):\n'
                '    if not nums:\n'
                '        return None\n'
                '    mn = min(nums)\n'
                '    mx = max(nums)\n'
                '    return [mn, mn]',
  'original_code': 'def find_min_max(nums):\n'
                   '    if not nums:\n'
                   '        return None\n'
                   '    mn = min(nums)\n'
                   '    mx = max(nums)\n'
                   '    return [mn, mx]',
  'initial_error': 'AssertionError: expected (1, 5), got (1, 1)',
  'bug_location': {'function': 'find_min_max', 'line_start': 6},
  'test_cases': [{'input': [[1, 2, 5]], 'expected_output': [1, 5]},
                 {'input': [[3, 3]], 'expected_output': [3, 3]},
                 {'input': [[-1, 0, 1]], 'expected_output': [-1, 1]},
                 {'input': [[]], 'expected_output': None}]},
 {'id': 't2_027',
  'difficulty': 2,
  'bug_type': 'wrong_variable',
  'function_name': 'remove_evens',
  'buggy_code': 'def remove_evens(nums):\n'
                '    res = []\n'
                '    for n in nums:\n'
                '        if n % 2 != 0:\n'
                '            res.append(n)\n'
                '    return nums',
  'original_code': 'def remove_evens(nums):\n'
                   '    res = []\n'
                   '    for n in nums:\n'
                   '        if n % 2 != 0:\n'
                   '            res.append(n)\n'
                   '    return res',
  'initial_error': 'AssertionError: expected [1, 3], got [1, 2, 3]',
  'bug_location': {'function': 'remove_evens', 'line_start': 6},
  'test_cases': [{'input': [[1, 2, 3]], 'expected_output': [1, 3]},
                 {'input': [[2, 4]], 'expected_output': []},
                 {'input': [[1, 3]], 'expected_output': [1, 3]},
                 {'input': [[]], 'expected_output': []}]},
 {'id': 't2_028',
  'difficulty': 2,
  'bug_type': 'wrong_variable',
  'function_name': 'duplicate_list',
  'buggy_code': 'def duplicate_list(lst):\n    res = lst[:]\n    res.extend(lst)\n    return lst',
  'original_code': 'def duplicate_list(lst):\n    res = lst[:]\n    res.extend(lst)\n    return res',
  'initial_error': 'AssertionError: expected [1, 1], got [1]',
  'bug_location': {'function': 'duplicate_list', 'line_start': 4},
  'test_cases': [{'input': [[1]], 'expected_output': [1, 1]},
                 {'input': [[1, 2]], 'expected_output': [1, 2, 1, 2]},
                 {'input': [[]], 'expected_output': []},
                 {'input': [[0]], 'expected_output': [0, 0]}]},
 {'id': 't2_029',
  'difficulty': 2,
  'bug_type': 'wrong_variable',
  'function_name': 'swap_halves',
  'buggy_code': 'def swap_halves(lst):\n'
                '    mid = len(lst) // 2\n'
                '    left = lst[:mid]\n'
                '    right = lst[mid:]\n'
                '    return left + left',
  'original_code': 'def swap_halves(lst):\n'
                   '    mid = len(lst) // 2\n'
                   '    left = lst[:mid]\n'
                   '    right = lst[mid:]\n'
                   '    return right + left',
  'initial_error': 'AssertionError: expected [3, 4, 1, 2], got [1, 2, 1, 2]',
  'bug_location': {'function': 'swap_halves', 'line_start': 5},
  'test_cases': [{'input': [[1, 2, 3, 4]], 'expected_output': [3, 4, 1, 2]},
                 {'input': [[1, 2, 3]], 'expected_output': [2, 3, 1]},
                 {'input': [[1]], 'expected_output': [1]},
                 {'input': [[]], 'expected_output': []}]},
 {'id': 't2_030',
  'difficulty': 2,
  'bug_type': 'wrong_variable',
  'function_name': 'get_initials',
  'buggy_code': 'def get_initials(name):\n'
                '    words = name.split()\n'
                '    initials = [w[0].upper() for w in words]\n'
                "    return ''.join(words)",
  'original_code': 'def get_initials(name):\n'
                   '    words = name.split()\n'
                   '    initials = [w[0].upper() for w in words]\n'
                   "    return ''.join(initials)",
  'initial_error': "AssertionError: expected 'JD', got 'JohnDoe'",
  'bug_location': {'function': 'get_initials', 'line_start': 4},
  'test_cases': [{'input': ['John Doe'], 'expected_output': 'JD'},
                 {'input': ['Alice'], 'expected_output': 'A'},
                 {'input': ['bob smith junior'], 'expected_output': 'BSJ'},
                 {'input': [''], 'expected_output': ''}]}]

TIER3_BUGS = [{'id': 't3_001',
  'difficulty': 3,
  'bug_type': 'edge_case_only',
  'function_name': 'merge_sorted',
  'buggy_code': 'def merge_sorted(a, b):\n'
                '    result = []\n'
                '    i = j = 0\n'
                '    while i < len(a) and j < len(b):\n'
                '        if a[i] <= b[j]:\n'
                '            result.append(a[i])\n'
                '            i += 1\n'
                '        else:\n'
                '            result.append(b[j])\n'
                '            j += 1\n'
                '    return result',
  'original_code': 'def merge_sorted(a, b):\n'
                   '    result = []\n'
                   '    i = j = 0\n'
                   '    while i < len(a) and j < len(b):\n'
                   '        if a[i] <= b[j]:\n'
                   '            result.append(a[i])\n'
                   '            i += 1\n'
                   '        else:\n'
                   '            result.append(b[j])\n'
                   '            j += 1\n'
                   '    result.extend(a[i:])\n'
                   '    result.extend(b[j:])\n'
                   '    return result',
  'initial_error': 'AssertionError: merge_sorted([1,3],[2,4,5]) expected [1,2,3,4,5], got [1,2,3]',
  'bug_location': {'function': 'merge_sorted', 'line_start': 11},
  'test_cases': [{'input': [[1, 3], [2, 4, 5]], 'expected_output': [1, 2, 3, 4, 5]},
                 {'input': [[], [1, 2]], 'expected_output': [1, 2]},
                 {'input': [[1, 2], []], 'expected_output': [1, 2]},
                 {'input': [[1], [2]], 'expected_output': [1, 2]}]},
 {'id': 't3_002',
  'difficulty': 3,
  'bug_type': 'subtle_logic',
  'function_name': 'rotate_matrix',
  'buggy_code': 'def rotate_matrix(matrix):\n'
                '    n = len(matrix)\n'
                '    for i in range(n):\n'
                '        for j in range(i, n):\n'
                '            matrix[i][j], matrix[j][i] = matrix[j][i], matrix[i][j]\n'
                '    return matrix',
  'original_code': 'def rotate_matrix(matrix):\n'
                   '    n = len(matrix)\n'
                   '    for i in range(n):\n'
                   '        for j in range(i, n):\n'
                   '            matrix[i][j], matrix[j][i] = matrix[j][i], matrix[i][j]\n'
                   '    for row in matrix:\n'
                   '        row.reverse()\n'
                   '    return matrix',
  'initial_error': 'AssertionError: rotate_matrix([[1,2],[3,4]]) expected [[3,1],[4,2]], got [[1,3],[2,4]]',
  'bug_location': {'function': 'rotate_matrix', 'line_start': 6},
  'test_cases': [{'input': [[[1, 2], [3, 4]]], 'expected_output': [[3, 1], [4, 2]]},
                 {'input': [[[1, 2, 3], [4, 5, 6], [7, 8, 9]]], 'expected_output': [[7, 4, 1], [8, 5, 2], [9, 6, 3]]}]},
 {'id': 't3_003',
  'difficulty': 3,
  'bug_type': 'wrong_argument_order',
  'function_name': 'process_user',
  'buggy_code': 'def format_name(first, last):\n'
                "    return f'{last}, {first}'\n"
                '\n'
                'def process_user(first_name, last_name):\n'
                '    return format_name(last_name, first_name)',
  'original_code': 'def format_name(first, last):\n'
                   "    return f'{last}, {first}'\n"
                   '\n'
                   'def process_user(first_name, last_name):\n'
                   '    return format_name(first_name, last_name)',
  'initial_error': "AssertionError: expected 'Doe, John', got 'John, Doe'",
  'bug_location': {'function': 'process_user', 'line_start': 5},
  'test_cases': [{'input': ['John', 'Doe'], 'expected_output': 'Doe, John'},
                 {'input': ['Alice', 'Smith'], 'expected_output': 'Smith, Alice'},
                 {'input': ['A', 'B'], 'expected_output': 'B, A'},
                 {'input': ['X', 'Y'], 'expected_output': 'Y, X'}]},
 {'id': 't3_004',
  'difficulty': 3,
  'bug_type': 'wrong_argument_order',
  'function_name': 'calculate_total',
  'buggy_code': 'def apply_discount(price, discount):\n'
                '    return price - (price * discount)\n'
                '\n'
                'def calculate_total(price, discount_rate):\n'
                '    return apply_discount(discount_rate, price)',
  'original_code': 'def apply_discount(price, discount):\n'
                   '    return price - (price * discount)\n'
                   '\n'
                   'def calculate_total(price, discount_rate):\n'
                   '    return apply_discount(price, discount_rate)',
  'initial_error': 'AssertionError: expected 80.0, got -19.8',
  'bug_location': {'function': 'calculate_total', 'line_start': 5},
  'test_cases': [{'input': [100, 0.2], 'expected_output': 80.0},
                 {'input': [50, 0.1], 'expected_output': 45.0},
                 {'input': [200, 0.5], 'expected_output': 100.0},
                 {'input': [10, 0.0], 'expected_output': 10.0}]},
 {'id': 't3_005',
  'difficulty': 3,
  'bug_type': 'wrong_argument_order',
  'function_name': 'build_url',
  'buggy_code': 'def join_parts(domain, path):\n'
                "    return f'https://{domain}/{path}'\n"
                '\n'
                'def build_url(domain, path):\n'
                '    return join_parts(path, domain)',
  'original_code': 'def join_parts(domain, path):\n'
                   "    return f'https://{domain}/{path}'\n"
                   '\n'
                   'def build_url(domain, path):\n'
                   '    return join_parts(domain, path)',
  'initial_error': "AssertionError: expected 'https://example.com/api', got 'https://api/example.com'",
  'bug_location': {'function': 'build_url', 'line_start': 5},
  'test_cases': [{'input': ['example.com', 'api'], 'expected_output': 'https://example.com/api'},
                 {'input': ['google.com', 'search'], 'expected_output': 'https://google.com/search'},
                 {'input': ['a.com', 'b'], 'expected_output': 'https://a.com/b'},
                 {'input': ['x.org', 'y'], 'expected_output': 'https://x.org/y'}]},
 {'id': 't3_006',
  'difficulty': 3,
  'bug_type': 'wrong_argument_order',
  'function_name': 'divide_numbers',
  'buggy_code': 'def safe_divide(num, den):\n'
                '    if den == 0:\n'
                '        return 0\n'
                '    return num / den\n'
                '\n'
                'def divide_numbers(a, b):\n'
                '    return safe_divide(b, a)',
  'original_code': 'def safe_divide(num, den):\n'
                   '    if den == 0:\n'
                   '        return 0\n'
                   '    return num / den\n'
                   '\n'
                   'def divide_numbers(a, b):\n'
                   '    return safe_divide(a, b)',
  'initial_error': 'AssertionError: expected 2.0, got 0.5',
  'bug_location': {'function': 'divide_numbers', 'line_start': 7},
  'test_cases': [{'input': [10, 5], 'expected_output': 2.0},
                 {'input': [5, 0], 'expected_output': 0},
                 {'input': [100, 10], 'expected_output': 10.0},
                 {'input': [0, 5], 'expected_output': 0.0}]},
 {'id': 't3_007',
  'difficulty': 3,
  'bug_type': 'wrong_argument_order',
  'function_name': 'create_rectangle',
  'buggy_code': 'def calc_area(w, h):\n'
                '    return w * h\n'
                '\n'
                'def create_rectangle(width, height):\n'
                "    return {'w': width, 'h': height, 'area': calc_area(height, height)}",
  'original_code': 'def calc_area(w, h):\n'
                   '    return w * h\n'
                   '\n'
                   'def create_rectangle(width, height):\n'
                   "    return {'w': width, 'h': height, 'area': calc_area(width, height)}",
  'initial_error': "AssertionError: doesn't strictly fail math but conceptually wrong",
  'bug_location': {'function': 'create_rectangle', 'line_start': 5},
  'test_cases': [{'input': [5, 10], 'expected_output': {'w': 5, 'h': 10, 'area': 50}},
                 {'input': [2, 3], 'expected_output': {'w': 2, 'h': 3, 'area': 6}},
                 {'input': [1, 1], 'expected_output': {'w': 1, 'h': 1, 'area': 1}},
                 {'input': [0, 5], 'expected_output': {'w': 0, 'h': 5, 'area': 0}}]},
 {'id': 't3_008',
  'difficulty': 3,
  'bug_type': 'wrong_argument_order',
  'function_name': 'power_wrapper',
  'buggy_code': 'def compute_pow(base, exp):\n'
                '    return base ** exp\n'
                '\n'
                'def power_wrapper(base, exp):\n'
                '    return compute_pow(exp, base)',
  'original_code': 'def compute_pow(base, exp):\n'
                   '    return base ** exp\n'
                   '\n'
                   'def power_wrapper(base, exp):\n'
                   '    return compute_pow(base, exp)',
  'initial_error': 'AssertionError: expected 8, got 9',
  'bug_location': {'function': 'power_wrapper', 'line_start': 5},
  'test_cases': [{'input': [2, 3], 'expected_output': 8},
                 {'input': [3, 2], 'expected_output': 9},
                 {'input': [5, 2], 'expected_output': 25},
                 {'input': [2, 4], 'expected_output': 16}]},
 {'id': 't3_009',
  'difficulty': 3,
  'bug_type': 'state_not_reset',
  'function_name': 'get_unique_items',
  'buggy_code': 'seen = {1}\n'
                'def filter_unique(items):\n'
                '    res = []\n'
                '    for item in items:\n'
                '        if item not in seen:\n'
                '            seen.add(item)\n'
                '            res.append(item)\n'
                '    return res\n'
                '\n'
                'def get_unique_items(items):\n'
                '    return filter_unique(items)',
  'original_code': 'def filter_unique(items, seen):\n'
                   '    res = []\n'
                   '    for item in items:\n'
                   '        if item not in seen:\n'
                   '            seen.add(item)\n'
                   '            res.append(item)\n'
                   '    return res\n'
                   '\n'
                   'def get_unique_items(items):\n'
                   '    return filter_unique(items, set())',
  'initial_error': 'AssertionError: test fails on second call',
  'bug_location': {'function': 'filter_unique', 'line_start': 4},
  'test_cases': [{'input': [[1, 2, 2, 3]], 'expected_output': [1, 2, 3]},
                 {'input': [[1, 2, 2, 3]], 'expected_output': [1, 2, 3]},
                 {'input': [[4, 4, 5]], 'expected_output': [4, 5]},
                 {'input': [[4, 4, 5]], 'expected_output': [4, 5]}]},
 {'id': 't3_010',
  'difficulty': 3,
  'bug_type': 'state_not_reset',
  'function_name': 'accumulate_values',
  'buggy_code': 'total = 10\n'
                'def add_to_total(val):\n'
                '    global total\n'
                '    total += val\n'
                '    return total\n'
                '\n'
                'def accumulate_values(vals):\n'
                '    return [add_to_total(v) for v in vals]',
  'original_code': 'def accumulate_values(vals):\n'
                   '    total = 0\n'
                   '    res = []\n'
                   '    for v in vals:\n'
                   '        total += v\n'
                   '        res.append(total)\n'
                   '    return res',
  'initial_error': 'AssertionError: expected [1, 3], got [1, 3] then [4, 6] on next call',
  'bug_location': {'function': 'add_to_total', 'line_start': 4},
  'test_cases': [{'input': [[1, 2]], 'expected_output': [1, 3]},
                 {'input': [[1, 2]], 'expected_output': [1, 3]},
                 {'input': [[5, 5]], 'expected_output': [5, 10]},
                 {'input': [[5, 5]], 'expected_output': [5, 10]}]},
 {'id': 't3_011',
  'difficulty': 3,
  'bug_type': 'state_not_reset',
  'function_name': 'append_to_default',
  'buggy_code': 'def helper(val, lst=[1]):\n'
                '    lst.append(val)\n'
                '    return lst\n'
                '\n'
                'def append_to_default(val):\n'
                '    return helper(val)',
  'original_code': 'def helper(val, lst=None):\n'
                   '    if lst is None:\n'
                   '        lst = []\n'
                   '    lst.append(val)\n'
                   '    return lst\n'
                   '\n'
                   'def append_to_default(val):\n'
                   '    return helper(val)',
  'initial_error': 'AssertionError: expected [2], got [1, 2]',
  'bug_location': {'function': 'helper', 'line_start': 1},
  'test_cases': [{'input': [1], 'expected_output': [1]},
                 {'input': [2], 'expected_output': [2]},
                 {'input': [3], 'expected_output': [3]},
                 {'input': [4], 'expected_output': [4]}]},
 {'id': 't3_012',
  'difficulty': 3,
  'bug_type': 'state_not_reset',
  'function_name': 'count_calls',
  'buggy_code': 'calls = 5\n'
                'def tracker():\n'
                '    global calls\n'
                '    calls += 1\n'
                '    return calls\n'
                '\n'
                'def count_calls(n):\n'
                '    res = []\n'
                '    for _ in range(n):\n'
                '        res.append(tracker())\n'
                '    return res',
  'original_code': 'def count_calls(n):\n'
                   '    calls = 0\n'
                   '    res = []\n'
                   '    for _ in range(n):\n'
                   '        calls += 1\n'
                   '        res.append(calls)\n'
                   '    return res',
  'initial_error': 'AssertionError: expected [1, 2], got [3, 4] on second run',
  'bug_location': {'function': 'tracker', 'line_start': 4},
  'test_cases': [{'input': [2], 'expected_output': [1, 2]},
                 {'input': [2], 'expected_output': [1, 2]},
                 {'input': [3], 'expected_output': [1, 2, 3]},
                 {'input': [3], 'expected_output': [1, 2, 3]}]},
 {'id': 't3_013',
  'difficulty': 3,
  'bug_type': 'state_not_reset',
  'function_name': 'build_sentence',
  'buggy_code': "words_cache = ['ERROR']\n"
                'def add_word(w):\n'
                '    words_cache.append(w)\n'
                "    return ' '.join(words_cache)\n"
                '\n'
                'def build_sentence(words):\n'
                "    res = ''\n"
                '    for w in words:\n'
                '        res = add_word(w)\n'
                '    return res',
  'original_code': 'def build_sentence(words):\n'
                   '    words_cache = []\n'
                   '    def add_word(w):\n'
                   '        words_cache.append(w)\n'
                   "        return ' '.join(words_cache)\n"
                   "    res = ''\n"
                   '    for w in words:\n'
                   '        res = add_word(w)\n'
                   '    return res',
  'initial_error': "AssertionError: expected 'hello world', got '... hello world'",
  'bug_location': {'function': 'add_word', 'line_start': 3},
  'test_cases': [{'input': [['hello', 'world']], 'expected_output': 'hello world'},
                 {'input': [['foo', 'bar']], 'expected_output': 'foo bar'},
                 {'input': [['a', 'b', 'c']], 'expected_output': 'a b c'},
                 {'input': [['x']], 'expected_output': 'x'}]},
 {'id': 't3_014',
  'difficulty': 3,
  'bug_type': 'state_not_reset',
  'function_name': 'collect_errors',
  'buggy_code': "errors = ['fatal']\n"
                'def log_error(err):\n'
                '    errors.append(err)\n'
                '    return errors\n'
                '\n'
                'def collect_errors(err_list):\n'
                '    for e in err_list:\n'
                '        res = log_error(e)\n'
                '    return res if err_list else []',
  'original_code': 'def collect_errors(err_list):\n'
                   '    errors = []\n'
                   '    def log_error(err):\n'
                   '        errors.append(err)\n'
                   '        return errors\n'
                   '    res = []\n'
                   '    for e in err_list:\n'
                   '        res = log_error(e)\n'
                   '    return res',
  'initial_error': 'AssertionError: state leak between calls',
  'bug_location': {'function': 'log_error', 'line_start': 3},
  'test_cases': [{'input': [['e1']], 'expected_output': ['e1']},
                 {'input': [['e2']], 'expected_output': ['e2']},
                 {'input': [['e3', 'e4']], 'expected_output': ['e3', 'e4']},
                 {'input': [['e5']], 'expected_output': ['e5']}]},
 {'id': 't3_015',
  'difficulty': 3,
  'bug_type': 'missing_edge_case',
  'function_name': 'process_data',
  'buggy_code': 'def get_first(lst):\n'
                '    return lst[0]\n'
                '\n'
                'def process_data(data):\n'
                '    if not data:\n'
                '        return None\n'
                '    return [get_first(d) for d in data]',
  'original_code': 'def get_first(lst):\n'
                   '    if not lst:\n'
                   '        return None\n'
                   '    return lst[0]\n'
                   '\n'
                   'def process_data(data):\n'
                   '    if not data:\n'
                   '        return []\n'
                   '    return [get_first(d) for d in data]',
  'initial_error': 'IndexError: list index out of range',
  'bug_location': {'function': 'get_first', 'line_start': 2},
  'test_cases': [{'input': [[[1, 2], [3, 4]]], 'expected_output': [1, 3]},
                 {'input': [[[1], []]], 'expected_output': [1, None]},
                 {'input': [[[], [2]]], 'expected_output': [None, 2]},
                 {'input': [[]], 'expected_output': []}]},
 {'id': 't3_016',
  'difficulty': 3,
  'bug_type': 'missing_edge_case',
  'function_name': 'average_scores',
  'buggy_code': 'def calc_avg(scores):\n'
                '    return sum(scores) / len(scores)\n'
                '\n'
                'def average_scores(students):\n'
                '    return {k: calc_avg(v) for k, v in students.items()}',
  'original_code': 'def calc_avg(scores):\n'
                   '    if not scores:\n'
                   '        return 0\n'
                   '    return sum(scores) / len(scores)\n'
                   '\n'
                   'def average_scores(students):\n'
                   '    return {k: calc_avg(v) for k, v in students.items()}',
  'initial_error': 'ZeroDivisionError: division by zero',
  'bug_location': {'function': 'calc_avg', 'line_start': 2},
  'test_cases': [{'input': [{'Alice': [10, 20], 'Bob': []}], 'expected_output': {'Alice': 15.0, 'Bob': 0}},
                 {'input': [{'A': [5]}], 'expected_output': {'A': 5.0}},
                 {'input': [{}], 'expected_output': {}},
                 {'input': [{'B': []}], 'expected_output': {'B': 0}}]},
 {'id': 't3_017',
  'difficulty': 3,
  'bug_type': 'missing_edge_case',
  'function_name': 'find_max_nested',
  'buggy_code': 'def find_max(lst):\n'
                '    return max(lst)\n'
                '\n'
                'def find_max_nested(nested_lists):\n'
                '    return [find_max(l) for l in nested_lists]',
  'original_code': 'def find_max(lst):\n'
                   '    if not lst:\n'
                   '        return None\n'
                   '    return max(lst)\n'
                   '\n'
                   'def find_max_nested(nested_lists):\n'
                   '    return [find_max(l) for l in nested_lists]',
  'initial_error': 'ValueError: max() arg is an empty sequence',
  'bug_location': {'function': 'find_max', 'line_start': 2},
  'test_cases': [{'input': [[[1, 2], []]], 'expected_output': [2, None]},
                 {'input': [[[1], [2, 3]]], 'expected_output': [1, 3]},
                 {'input': [[[], []]], 'expected_output': [None, None]},
                 {'input': [[]], 'expected_output': []}]},
 {'id': 't3_018',
  'difficulty': 3,
  'bug_type': 'missing_edge_case',
  'function_name': 'get_extensions',
  'buggy_code': 'def extract_ext(filename):\n'
                "    return filename.split('.')[1]\n"
                '\n'
                'def get_extensions(files):\n'
                '    return [extract_ext(f) for f in files]',
  'original_code': 'def extract_ext(filename):\n'
                   "    parts = filename.split('.')\n"
                   '    if len(parts) < 2:\n'
                   "        return ''\n"
                   '    return parts[-1]\n'
                   '\n'
                   'def get_extensions(files):\n'
                   '    return [extract_ext(f) for f in files]',
  'initial_error': 'IndexError: list index out of range',
  'bug_location': {'function': 'extract_ext', 'line_start': 2},
  'test_cases': [{'input': [['a.txt', 'b']], 'expected_output': ['txt', '']},
                 {'input': [['a.txt', 'b.pdf']], 'expected_output': ['txt', 'pdf']},
                 {'input': [['noext']], 'expected_output': ['']},
                 {'input': [[]], 'expected_output': []}]},
 {'id': 't3_019',
  'difficulty': 3,
  'bug_type': 'missing_edge_case',
  'function_name': 'get_lengths',
  'buggy_code': 'def get_len(item):\n'
                '    return len(item)\n'
                '\n'
                'def get_lengths(items):\n'
                '    return [get_len(i) for i in items]',
  'original_code': 'def get_len(item):\n'
                   '    if item is None:\n'
                   '        return 0\n'
                   '    return len(item)\n'
                   '\n'
                   'def get_lengths(items):\n'
                   '    return [get_len(i) for i in items]',
  'initial_error': "TypeError: object of type 'NoneType' has no len()",
  'bug_location': {'function': 'get_len', 'line_start': 2},
  'test_cases': [{'input': [['abc', None]], 'expected_output': [3, 0]},
                 {'input': [['a', 'b']], 'expected_output': [1, 1]},
                 {'input': [[None, None]], 'expected_output': [0, 0]},
                 {'input': [[]], 'expected_output': []}]},
 {'id': 't3_020',
  'difficulty': 3,
  'bug_type': 'missing_edge_case',
  'function_name': 'parse_integers',
  'buggy_code': 'def to_int(s):\n'
                '    return int(s)\n'
                '\n'
                'def parse_integers(strings):\n'
                '    return [to_int(s) for s in strings]',
  'original_code': 'def to_int(s):\n'
                   '    try:\n'
                   '        return int(s)\n'
                   '    except ValueError:\n'
                   '        return 0\n'
                   '\n'
                   'def parse_integers(strings):\n'
                   '    return [to_int(s) for s in strings]',
  'initial_error': 'ValueError: invalid literal for int() with base 10',
  'bug_location': {'function': 'to_int', 'line_start': 2},
  'test_cases': [{'input': [['1', 'abc']], 'expected_output': [1, 0]},
                 {'input': [['1', '2']], 'expected_output': [1, 2]},
                 {'input': [['foo', 'bar']], 'expected_output': [0, 0]},
                 {'input': [[]], 'expected_output': []}]}]

def write_jsonl(bugs: list, path: str):
    with open(path, "w") as f:
        for bug in bugs:
            f.write(json.dumps(bug) + "\n")

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    write_jsonl(TIER1_BUGS, "data/bugs_tier1.jsonl")
    write_jsonl(TIER2_BUGS, "data/bugs_tier2.jsonl")
    write_jsonl(TIER3_BUGS, "data/bugs_tier3.jsonl")
    print(f"Tier 1: {len(TIER1_BUGS)}, Tier 2: {len(TIER2_BUGS)}, Tier 3: {len(TIER3_BUGS)}")
    print("\nDone. Run training/train_grpo.py to start training.")
