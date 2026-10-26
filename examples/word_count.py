text = "the cat saw the dog"
counts = {}
for word in text.split():
    counts[word] = counts.get(word, 0) + 1
print(counts)
