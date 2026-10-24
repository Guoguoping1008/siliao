"""把"表头重复 N 次"的幻觉表压成正常表(去掉重复列名)。

实测:
  0325: | 名称 | 英文名称 | 化学式或描述 | 来源 | 含量规格 | 含量规格 | ... (20 个"含量规格")
  0344: | 通用名称 | ... | 在配合饲料中的 | 在配合饲料中的 | ... (14 个)
  0547: | 序号 | 中文名 | 中文名 | CAS号 | ... | 每毫克分子量/μg x 15
  0096: | 抗菌药物类别 | ... | 细菌种类 x 17

这些是 OCR/VLM 把**跨列合并的一格**展开成了 N 个重复的列名。
处理: 把连续的同名列**合并成一个 colspan**。

坑: 只有**连续**的同名列才合并; 不连续的同名(像 0342 的
  "食品添加剂 | 复合配料 | 食品添加剂 | 复合配料 ...")是**两级表头**,
  不能合并 —— 那是"配料类别"下分出的子列。
"""
import re
from collections import Counter


def collapse_repeat_header(cells):
    """把连续重复的表头名合并 -> [(名称, span), ...]"""
    out = []
    i = 0
    n = len(cells)
    while i < n:
        v = cells[i]
        j = i + 1
        while j < n and cells[j] == v:
            j += 1
        out.append((v, j - i))
        i = j
    return out


def is_hallucinated_header(cells):
    """判断表头是否是"幻觉重复"。

    判据: 存在某个名字**连续出现 >= 3 次**且占了表头一半以上。
    (正常的两级表头是 A|B|A|B 交替, 不会连续重复)
    """
    if len(cells) < 4:
        return False
    pairs = collapse_repeat_header(cells)
    return any(span >= 3 and span >= len(cells) * 0.5 for _, span in pairs)
