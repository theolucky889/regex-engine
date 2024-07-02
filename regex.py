assert re_parse('') is None
assert re_parse('.') == 'dot'
assert re_parse('a') == 'a'
assert re_parse('ab') == ('cat', 'a', 'b')
assert re_parse('a|b') == ('split', 'a', 'b')
assert re_parse('a+') == ('repeat', 'a', 1, float('inf'))
assert re_parse('a{3,6}') == ('repeat', 'a', 3, 6)
assert re_parse('a|bc') == ('split', 'a', ('cat', 'b', 'c'))

# r = regex string
# idx = current parsing position

# a|b|c...
def parse_split(r, idx):
    idx, prev = parse_concat(r, idx)
    while idx < len(r):
        if r[idx] == ')':
            # return to the outside parse_node
            break
        assert r[idx] == '|', 'BUG'
        idx, node = parse_concat(r, idx + 1)
        prev = ('split', prev, node)
    return idx, prev

# abc...
def parse_concat(r, idx):
    prev = None
    while idx < len(r):
        if r[idx] in '|)':
            # return to the outer parse_split or parse_node
            break
        idx, node = parse_node(r, idx)
        if prev is None:
            prev = node
        else:
            prev = ('cat', prev, node)
    # when the prev is still None, it denotes the empty string
    return idx, prev

# parse a single element
def parse_node(r, idx):
    ch = r[idx]
    idx += 1
    assert ch not in '|)'
    if ch == '(':
        idx, node = parse_split(r, idx)
        if idx < len(r) and r[idx] == ')':
            idx += 1
        else:
            raise Exception('unbalance parenthesis')
    elif ch == '.':
        node = 'dot'
    elif ch in '*+{':
        raise Exception('nothing to repeat')
    else:
        node = ch
    
    idx, node = parse_postfix(r, idx, node)
    return idx, node      

# a*, a+, a{x}, a{x,}, a{x,y}
def parse_postfix(r, idx, node):
    if idx == len(r) or r[idx] not in '*+{':
        return idx, node
    
    ch = r[idx]
    idx += 1
    if ch == '*':
        rmin, rmax = 0, float('inf')
    elif ch == '+':
        rmin, rmax = 1, float('inf')
    else:
        # the first number inside the {}
        idx, i = parse_int(r, idx)
        if i is None:
            raise Exception('expect int')
        rmin = rmax = i
        # the optional second number
        if idx < len(r) and r[idx] == ',':
            idx, j = parse_int(r, idx + 1)
            rmax = j if (j is not None) else float('inf')
        # close the brace
        if idx < len(r) and r[idx] == '}':
            idx += 1
        else:
            raise Exception('unbalanced brace')
    
    # check
    if rmax < rmin:
        raise Exception('min repeat greater than max repeat')
    if rmin> RE_REPEAT_LIMIT:
        raise Exception('the repetition number is too large')
    
    node = ('repeat', node, rmin, rmax)
    return idx, node

def parse_int(r, idx):
    save = idx
    while idx < len(r) and r[idx].isdigit():
        idx += 1
    return idx, int(r[save:idx]) if save != idx else None

def re_parse(r):
    idx, node = parse_split(r, 0)
    if idx != len(r):
        # parsing stopped at a bad ")"
        raise Exception('unexpected ")"')
    return node

# backtracking regex
# the backtracking method is brute force method
# can also add some caching to eliminate duplicated idx
def match_backtrack(node, text, idx):
    if node is None:
        yield idx   # empty string
    elif node == 'dot':
        if idx < len(text):
            yield idx + 1
    elif isinstance(node, str):
        assert len(node) == 1   # single char
        if idx < len(text) and text[idx] == node:
            yield idx + 1
    elif node[0] == 'cat':
        # the 'yield from' is equivalent to: 
        # for idx1 in match_backtrack_concat(node, text, idx):
        #   yield idx1
        yield from match_backtrack_concat(node, text, idx)
    elif node[0] == 'split':
        yield from match_backtrack(node[1], text, idx)
        yield from match_backtrack(node[2], text, idx)
    elif node[0] == 'repeat':
        yield from match_backtrack_repeat(node, text, idx)
    else:
        assert not 'reachable'

def match_backtrack_concat(node, text, idx):
    met = set()
    for idx1 in match_backtrack(node[1], text, idx):
        if idx1 in met:
            continue    # duplication
        met.add(idx1)
        yield from match_backtrack(node[2], text, idx1)

def match_backtrack_repeat(node, text, idx):
    _, node, rmin, rmax = node
    rmax = min(rmax, RE_REPEAT_LIMIT)
    # output is buffered and reversed later
    output = []
    if rmin == 0:
        # dont have to match anything
        output.append(idx)
    # position from the previous step
    start = {idx}
    # try every possible repetition number
    for i in range(1, rmax + 1):
        found = set()
        for idx1 in start:
            for idx2 in match_backtrack(node, text, idx1):
                found.add(idx2)
                if i >= rmin:
                    output.append(idx2)
        # TODO: bail out if the only match is of zero-length
        if not found:
            break
        start = found
    # repetition is greedy, output is the most repetitive match first
    yield from reversed(output)
    
def re_full_match_bt(node, text):
    for idx in match_backtrack(node, text, 0):
        # idx is the size of the matched prefix
        if idx == len(text):
            # NOTE: the greedy aspect of regexes seems to be irrelevant
            #       if we are only accepting the fully matched text
            return True
        return False
    
# build a graph from a node
# the graph is entered/exited via the start/end node
# the id2node is a mapping from integer IDs to the graph nodes
# the graph node is either a list of links or a special "boss" node
def nfa_make(node, start, end, id2node):
    if node is None:
        start.append((None, end))
    elif node == 'dot':
        start.append(('dot', end))
    elif isinstance(node, str):
        start.append((node, end))
    elif node[0] == 'cat':
        # connect the two subgraphs via a middle node
        middle = []
        id2node[id(middle)] = middle
        nfa_make(node[1], start, middle, id2node)
        nfa_make(node[2], middle, end, id2node)
    elif node[0] == 'split':
        # connect with both subgraphs
        nfa_make(node[1], start, end, id2node)
        nfa_make(node[2], start, end, id2node)
    elif node[0] == 'repeat':
        nfa_make_repeat(node, start, end, id2node)
    else:
        assert not 'reachable'

def nfa_make_repeat(node, start, end, id2node):
    # unpack
    _, node, rmin, rmax = node
    rmax = min(rmax, RE_REPEAT_LIMIT)
    # the door_in only leads to the subgraph,
    # it is necessary for repetitions to work
    door_in = []
    # the door_out leads to either the door_in or the end
    door_out = ('boss', door_in, end, rmin, rmax)
    id2node[id(door_in)] = door_in
    id2node[id(door_out)] = door_out
    # the subgraph between the door_in and the door_out
    nfa_make(node, door_in, door_out, id2node)
    # links from the start node
    start.append((None, door_in))
    if rmin == 0:
        start.append((None, end))

# Traversing the graph
def re_full_match_nfa(node, text):
    # build the graph
    start, end = [], []
    id2node = {id(start): start, id(end): end}
    nfa_make(node, start, end, id2node)
    # explore and expand the initial position set
    node_set = {id(start, ())}
    nfa_expand(node_set, id2node)
    for ch in text:
        # move to the next position set
        node_set = nfa_step(node_set, ch, id2node)
        nfa_expand(node_set, id2node)
    return (id(end), ()) in node_set

# the next position set from the input character
def nfa_step(node_set, ch, id2node):
    assert len(ch) == 1
    next_nodes = set()
    for node, kv in node_set:
        node = id2node[node]
        # only normal nodes since bosses were handled by the nfa_expand
        assert not isinstance(node, tuple), 'unexpected boss'
        for cond, dst in node:
            if cond == 'dot' or cond == ch:
                next_nodes.add((id(dst), kv))
    return next_nodes

# expand the position set via free links and boss nodes
def nfa_expand(node_set, id2node):
    start = list(node_set)
    while start:
        new_nodes = []
        for node, kv in start:
            node = id2node[node]
            if isinstance(node, tuple) and node[0] == 'boss':
                # a boss, replace it with the outcome
                node_set.remove((id(node), kv))
                for dst, kv in nfa_boss(node, kv):
                    new_nodes.append((id(dst), kv))
            else:
                # explore new nodes via free links
                for cond, dst in node:
                    if cond is None:
                        new_nodes.append((id(dst), kv))
                        
        # newly added nodes will be used for the next iteration
        start = []
        for state in new_nodes:
            if state not in node_set:
                node_set.add(state)
                start.append(state)

def nfa_boss(node, kv):
    _, door_in, end, rmin, rmax = node
    key = id(door_in)   # this is unique for identifying the boss
    kv, cnt = kv_increase(kv, key)
    if cnt < rmax:
        # repeat the level again
        yield (door_in, kv)
    if rmin <= cnt <= rmax:
        # pass the level
        yield (end, kv_delete(kv, key))

def kv_increase(kv, key):
    kv = dict(kv)
    val = kv.get(key, 0) + 1
    kv[key] = val
    return tuple(sorted(kv.items())), val

def kv_delete(kv, key):
    return tuple((k, v) for k, v in kv if k!= key)