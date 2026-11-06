"""发布前自动审核（V6第20.11节）。用法：python3 -I tools/audit_recommendations.py final.json
final.json格式：
{"groups":[{"name":"足球晚场②","sport":"football","legs":[{"num":"周三005","market":"HAD","L":"0",
   "options":[{"key":"a","label":"客胜","odds":"1.35"}],"reasons":["...","..."]}, ...]}],
 "dream":[{"num":"周三012","score":"1:2","odds":"7.00"}]}
market：HAD/HHAD/TTG/DD/HAFU（足球），MNL/HDC/HILO（篮球）。DD的key为had_d/hhad_d；TTG的key为s0..s7；HAFU为hh/hd/...
不通过时退出码1。审核逻辑在 src/foot_web/services/audit.py。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from foot_web.services.audit import audit  # noqa: E402


def main(path):
    errs, notes = audit(json.loads(Path(path).read_text()))
    for x in notes: print('OK  ', x)
    for x in errs: print('FAIL', x)
    print('审核结果：', '不通过' if errs else '通过')
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
