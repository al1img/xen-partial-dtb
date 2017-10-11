#!/usr/bin/python

import argparse
import re
from pyfdt.pyfdt import *
from pip.cmdoptions import src

# constant
GIC_SPI = 0
GIC_PPI = 1
IRQ_BASE = 32
PAGE_SHIFT = 12
PAGE_SIZE = (1 << PAGE_SHIFT)

def match_list(l, value):
    for entry in l:
        m = entry.match(value)
        if m:
            return True
    return False

def is_node_ok(path, node):
    try:
        if match_list(black_list, path):
            print 'Warning: item %s is in black list' % (path)
            return False;
        index = node.index('status')
        if isinstance(node[index], FdtPropertyStrings) and (node[index][0] == 'disabled'):
            print 'Warning: item %s disabled' % (node.get_name()) 
            return False
        return True
    except ValueError:
        return True

def write_compatible(fdt, file):
    result = ""
    node = fdt.resolve_path('/compatible')
    if node and isinstance(node, FdtPropertyStrings):
        result += 'dt_compatible = [ "' + '", "'.join(node) + '" ]\n\n'
    file.write(result)

def get_iommus(path, node):
    result = ""
    if not is_node_ok(path, node):
        return result
    if node._find('iommus') and not node._find('xen,coproc'):
        result = '    "' + path + '",\n'
    return result

def write_iommus(fdt, file):
    print 'Info: generate dtdev'
    file.write('dtdev = [\n')
    for (path, node) in fdt.resolve_path('/').walk():
        if isinstance(node, FdtNode): 
            file.write(get_iommus(path, node))
    file.write(']\n\n')

def get_irqs(path, node):
    result = ""
    if not is_node_ok(path, node):
        return result
    first = True
    for (item) in node:
        if isinstance(item, FdtPropertyWords):
            if item.get_name() == 'interrupts':
                for (spec, num, mask) in zip(item[::3], item[1::3], item[2::3]):
                    if spec == GIC_SPI:
                        if first:
                            result += '# ' + node.get_name() + '\n    '
                            first = False
                        result += str(num + IRQ_BASE) + ', '
    if not first:
        result += '\n'
    return result

def write_irqs(fdt, file):
    print 'Info: generate irqs'
    file.write('irqs = [\n')
    for (path, node) in fdt.resolve_path('/').walk():
        if isinstance(node, FdtNode): 
            file.write(get_irqs(path, node))
    file.write(']\n\n')

def get_regs(path, node):
    result = list()
    if not is_node_ok(path, node):
        return result
    for (item) in node:
        if isinstance(item, FdtPropertyWords):
            if item.get_name() == 'reg':
                for (val) in zip(item[::4], item[1::4], item[2::4], item[3::4]):
                    if val[0] == 0:
                        result.append((val[1] >> PAGE_SHIFT, (val[3] + PAGE_SIZE - 1) // PAGE_SIZE, node.get_name()))
    return result

def add_reg(regs, val):
    for (i, r) in enumerate(regs):
        if r[0] == val[0]:
            regs[i][2].append(val[2])
            return
    names = list()
    names.append(val[2])
    regs.append((val[0], val[1], names))

def write_regs(fdt, file):
    result = list()
    file.write('iomem = [\n')
    for (path, node) in fdt.resolve_path('/').walk():
        if isinstance(node, FdtNode):
            for val in get_regs(path, node):
                add_reg(result, val)

    for (addr, size, names) in result:
        for name in names:
            file.write('#' + name + '\n')
        file.write('    "%05x,%x",\n' % (addr, size))
    file.write(']\n\n')

def add_passthrough(fdt):
    prop = FdtProperty('xen,passthrough')
    for (path, node) in fdt.resolve_path('/').walk():
        if isinstance(node, FdtNode): 
            if not is_node_ok(path, node):
                continue
            if node._find('iommus') or node._find('interrupts'):
                if node._find('xen,passthrough'):
                    print 'Warning: item %s passthrough already set' % node.get_name()
                else:
                    node.insert(node.index('iommus') + 1, prop)

def set_node_disabled(node):
    status = FdtPropertyStrings('status', ['disabled'])
    try:
        node[node.index('status')] = status
    except ValueError:
        node.add_subnode(status)

def partial_dtb_node(path, src_node, dst_node):
    for entry in src_node:
        entry_path = path + entry.get_name()
        if match_list(black_list, entry_path):
            print 'Warning: item %s is in black list' % entry_path
            continue
        match_disabled = match_list(disable_list, entry_path)
        match_dtb = match_list(dtb_list, entry_path)
        if len(dtb_list) == 0 or match_dtb or match_disabled:
            print 'Info: item %s is added to dtb' % entry_path
            if isinstance(entry, FdtNode):
                dst_entry = FdtNode(entry.get_name())
                dst_node.add_subnode(dst_entry)
                partial_dtb_node(entry_path + '/', entry, dst_entry)
                if match_disabled:
                    print 'Warning: item %s is disabled' % entry_path
                    set_node_disabled(dst_entry)
            if isinstance(entry, FdtProperty):
                dst_node.add_subnode(entry)

def partial_dtb(fdt):
    result = Fdt()
    result.add_rootnode(FdtNode("/"))
    partial_dtb_node('/', fdt.get_rootnode(), result.get_rootnode())
    return result;

def create_list(file_name):
    l = list()
    if not file_name:
        return l
    with open(file_name) as file:
        string_list = file.read().splitlines()
        for entry in string_list:
            if entry:
                l.append(re.compile(entry))
    return l

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Xen partial dtb')
    parser.add_argument('src_filename', help="source DTB filename")
    parser.add_argument('out_filename', help="output config filename")
    parser.add_argument('--action', help="specifies action to be performed",
                        required = True, choices=['config', 'passthrough', 'partialdtb'])
    parser.add_argument('--black_list', help="specifies black list file name")
    parser.add_argument('--disable_list', help="specifies disable list file name")
    parser.add_argument('--dtb_list', help="specifies dtb list file name")
    args = parser.parse_args()

    # create lists
    black_list = create_list(args.black_list)
    disable_list = create_list(args.disable_list)
    dtb_list = create_list(args.dtb_list)

    with open(args.src_filename) as infile:
        dtb = FdtBlobParse(infile)

    fdt = dtb.to_fdt()

    if args.action.lower() == 'config':
        with open(args.out_filename, "w") as outfile:
            write_compatible(fdt, outfile)
            write_iommus(fdt, outfile)
            write_irqs(fdt, outfile)
            write_regs(fdt, outfile)
    elif args.action.lower() == 'passthrough':
        with open(args.out_filename, "w") as outfile:
            add_passthrough(fdt)
            outfile.write(fdt.to_dtb())
    elif args.action.lower() == 'partialdtb':
        with open(args.out_filename, "w") as outfile:
            result =  partial_dtb(fdt).to_dtb()
            if result:
                outfile.write(result)
    else:
        raise ValueError('Invalid action %s' % args.action)