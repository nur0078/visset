def is_palindrome(text):
    """Check a word from both ends at once."""
    left, right = 0, len(text) - 1
    while left < right:
        if text[left] != text[right]:
            return False
        left += 1
        right -= 1
    return True


def longest_palindrome(words):
    best = ""
    for word in words:
        if is_palindrome(word) and len(word) > len(best):
            best = word
    return best


print(longest_palindrome(["kayak", "level", "racecar", "visset"]))
