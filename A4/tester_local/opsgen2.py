#!/usr/bin/env python3

import subprocess
import sys

def main():
	range_len = int(sys.argv[1])
	files_num = int(sys.argv[2])
	put_count = int(sys.argv[3])
	get_count = int(sys.argv[4])
	multiplier = int(sys.argv[5]) if len(sys.argv) > 5 else 1

	for i in range(files_num):
		filename = "./tests/ops_%d_%d_%d_%d_%d.txt" % (range_len, i, put_count, get_count, multiplier)
		print("generating %s ..." % (filename))
		subprocess.check_call("./opsgen.py %d %d %d %d %d > %s" %
		                      (range_len, i, put_count, get_count, multiplier, filename), shell=True)

main()
