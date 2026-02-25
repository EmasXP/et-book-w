from dataclasses import dataclass
from collections import defaultdict
from typing import Optional

kern_file = "kerning.fea"

stage = 0
before = []
after = []
map = defaultdict(dict)

@dataclass
class Entry:
	first_char: str
	second_char: str
	kern: str
	comment_line: Optional[str]

with open(kern_file) as fh:
	for line in fh:
		pos_line = line.strip().split(" ", 4)

		if stage == 0:
			if pos_line[0] == "pos":
				stage = 1
			else:
				before.append(line)
				continue

		if stage == 1:
			if len(line.strip()) == 0:
				continue
			if pos_line[0] != "pos":
				stage = 2
			else:
				first_char = pos_line[1]
				first_char_sort = first_char
				second_char = pos_line[2]
				second_char_sort = second_char
				kern = pos_line[3].strip()
				comment_line = pos_line[4] if len(pos_line) > 4 else None
				if comment_line:
					comment_line = comment_line.strip()
				if comment_line:
					if comment_line[0] != "#":
						raise Exception("Unexpected comment part: "+comment_line)
					comment_parts = comment_line.split()
					if len(comment_parts) > 2:
						a = comment_parts[-3]
						b = comment_parts[-2]
						c = comment_parts[-1]
						if a == "#" and len(b) == 1 and len(c) == 1:
							first_char_sort = b
							second_char_sort = c
				map[first_char_sort][second_char_sort] = Entry(
					first_char = first_char,
					second_char = second_char,
					kern = kern,
					comment_line = comment_line
				)
				continue

		if stage == 2:
			after.append(line)

out = "".join(before)

for _, second in sorted(map.items()):
	for _, entry in sorted(second.items()):
		out += "\tpos "+entry.first_char+" "+entry.second_char+" "+entry.kern
		if entry.comment_line:
			out += " "+entry.comment_line
		out += "\n"
	out += "\n"

out = out.rstrip()+"\n"
out += "".join(after)

with open(kern_file, "w") as fh:
	fh.write(out)
