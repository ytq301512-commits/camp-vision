"""Apply the card-tier values read from the provided faction screenshots."""

from __future__ import annotations

import json
from pathlib import Path


TIERS = {
    # 大河流域
    "干将莫邪": 1, "项羽": 2, "鬼谷子": 2, "虞姬": 2, "云中君": 3,
    "张良": 3, "少司缘": 3, "瑶": 3, "大司命": 4, "刘邦": 4,
    "韩信": 4, "东皇太一": 5, "敖隐": 5,
    # 逐鹿
    "曜": 1, "孙": 1, "芈月": 2, "墨子": 2, "廉颇": 2, "蒙恬": 2,
    "白起": 3, "老夫子": 3, "西施": 3, "镜": 4, "扁": 4,
    "嬴政": 4, "庄周": 4, "蒙": 4, "鲁班大师": 5, "鲁班七号": 5,
    # 三分之地
    "孙尚香": 1, "曹操": 2, "赵云": 2, "大乔": 2, "蔡文姬": 3,
    "马超": 3, "刘禅": 3, "貂蝉": 3, "甄姬": 4, "小乔": 4,
    "诸葛亮": 5, "吕布": 5, "周瑜": 5,
    # 河洛
    "苏烈": 1, "李元芳": 1, "沈梦溪": 2, "盾山": 2, "百里守约": 2,
    "百里玄策": 3, "铠": 3, "程咬金": 3, "狄仁杰": 3, "钟馗": 3,
    "上官婉儿": 4, "李信": 4, "李白": 4, "花木兰": 5, "司空震": 5,
    "武则天": 5,
    # 日落海
    "狂铁": 1, "亚连": 2, "米莱狄": 2, "马可波罗": 2, "姬小满": 3,
    "亚瑟": 3, "安琪拉": 3, "朵莉亚": 3, "莱西奥": 4, "艾琳": 4,
    "雅典娜": 4, "海诺": 5, "露娜": 5,
    # 无阵营
    "弈星": 1, "牛魔": 1, "梦奇": 2, "公孙离": 2, "苍": 3,
    "明世隐": 3, "阿轲": 3, "裴擒虎": 3, "猪八戒": 3, "太乙真人": 4,
    "孙悟空": 4, "姜子牙": 5, "海月": 5, "杨玉环": 5,
}


def update(path: Path) -> None:
    backup = path.with_name(path.name + ".bak")
    backup.write_bytes(path.read_bytes())
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    names = {str(item["name"]) for item in data["characters"]}
    missing = names - TIERS.keys()
    if missing:
        raise ValueError(f"Missing tier values: {', '.join(sorted(missing))}")
    for item in data["characters"]:
        camp = str(item["camp"])
        while camp and camp[0].isdigit():
            camp = camp[1:]
        item["camp"] = f"{TIERS[item['name']]}{camp}"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {len(data['characters'])} characters: {path}")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    update(Path(r"C:\Users\admin\Desktop\人物库.json"))
    update(root / "data" / "roster.json")
