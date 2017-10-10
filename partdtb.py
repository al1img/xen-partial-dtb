#!/usr/bin/python

import argparse
import re
from pyfdt.pyfdt import *

# constant
GIC_SPI = 0
GIC_PPI = 1
IRQ_BASE = 32
PAGE_SHIFT = 12
PAGE_SIZE = (1 << PAGE_SHIFT)

def is_node_ok(path, node):
    try:
        for entry in black_list:
            m = entry.match(path)
            if m:
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
        result += 'dt_compatible = [ "' + ', "'.join(node) + '" ]\n\n'
    file.write(result)

def get_iommus(path, node):
    result = ""
    if not is_node_ok(path, node):
        return result
    prop = FdtProperty("xen,passthrough")
    for (item) in node:
        if isinstance(item, FdtPropertyWords):
            if item.get_name() == 'iommus':
                result += '    "' + path + '",\n'
                node.insert(node.index('iommus') + 1, prop)
    return result

def write_iommus(fdt, file):
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
        file.write('"0x%05x,%x",\n' % (addr, size))
    file.write(']\n\n')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Xen partial dtb')
    parser.add_argument('src_filename', help="source DTB filename")
    parser.add_argument('out_filename', help="output config filename")
    parser.add_argument('dtb_filename', help="output DTB filename")
    parser.add_argument('--black_list', help="specifies black list file name")
    args = parser.parse_args()
    
    black_list = list()
    
    if args.black_list:
        with open(args.black_list) as bl_file:
            string_list = bl_file.read().splitlines()
            for entry in string_list:
                black_list.append(re.compile(entry))

    with open(args.src_filename) as infile:
        dtb = FdtBlobParse(infile)

    fdt = dtb.to_fdt()

    with open(args.out_filename, "w") as outfile:
        write_compatible(fdt, outfile)
        write_iommus(fdt, outfile)
        write_irqs(fdt, outfile)
        write_regs(fdt, outfile)

    with open(args.dtb_filename, "w") as outfile:
        outfile.write(fdt.to_dtb())
