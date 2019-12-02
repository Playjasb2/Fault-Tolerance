#!/usr/bin/env python3

import random
import string
import sys

key_length = 10
value_length = 100

def randstr(length):
	return "".join(random.choice(string.ascii_letters + string.digits) for i in range(length))

def write_op(type, key, value, count=1):
	print("%s \"%s\" \"%s\" %d" % (type, key, value, count))

def main():
	range_len = int(sys.argv[1])
	range_idx = int(sys.argv[2])
	put_count = int(sys.argv[3])
	get_count = int(sys.argv[4])
	multiplier = int(sys.argv[5]) if len(sys.argv) > 5 else 1

	key_ids = range(range_idx * range_len, (range_idx + 1) * range_len)
	keys = ["key_%d_%s" % (i, randstr(key_length)) for i in key_ids]
	values = ["value_%d_%s" % (i, randstr(value_length)) for i in key_ids]

	k = random.randint(0, range_len - 1)
	write_op("P", keys[k], values[k], multiplier)
	used_keys = [k]
	puts = 1

	get_prob = (1.0 * get_count) / (get_count + put_count)
	for i in range(put_count + get_count - 1):
		if (random.uniform(0.0, 1.0) > get_prob) and (puts < put_count):
			k = random.randint(0, range_len - 1)
			write_op("P", keys[k], values[k], multiplier)
			used_keys.append(k)
			puts += 1
		else:
			k = used_keys[random.randint(0, len(used_keys) - 1)]
			write_op("C", keys[k], values[k], multiplier)

main()
