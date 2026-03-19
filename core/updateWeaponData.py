import requests
import os
import csv
from bs4 import BeautifulSoup

weapon_url = 'https://wiki.biligame.com/zmd/%E6%AD%A6%E5%99%A8%E5%9B%BE%E9%89%B4'

# 目前阿B的wiki不需要cookies就能访问，暂时不去逆向页面研究这个cookies了
cookies = {
}

headers = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Pragma': 'no-cache',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"'
}


class UpdateWeapon:
    def __init__(self, dm, callbacks):
        self.dm = dm

        self.log_cb = callbacks.get('log', lambda m, t="black": None)
        self.lock_cb = callbacks.get('lock', lambda data: None)
        self.finish_cb = callbacks.get('finish', lambda: None)

        self.running = False

    def export_weapon_data(self, response, csv_filename=None):
        """
        从 response 解析武器表格，与现有 CSV 文件（如果存在）增量合并，
        只处理5/6星且三个词条齐全的武器，最终按“新增 → 修改 → 未变”顺序写入

        :param response: requests.Response 对象或 HTML 字符串
        :param csv_filename: 输出的 CSV 文件路径；若为 None，则使用默认路径 'data/weapon_data.csv'
        """
        # ---------- 确定 CSV 路径 ----------
        if csv_filename is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            csv_filename = os.path.join(base_dir, 'data', 'weapon_data.csv')

        # ---------- 1. 解析新数据 ----------
        html = response.text if hasattr(response, 'text') else response
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table', id='CardSelectTr')
        if not table or not table.find('tbody'):
            self.log_cb("[警告] 武器数据获取失败，跳过武器列表更新", "gold")
            return

        tbody = table.find('tbody')
        rows = tbody.find_all('tr')
        raw_new_data = []  # 临时存储所有解析出的武器信息

        for row in rows:
            tds = row.find_all('td')
            if len(tds) < 3:
                continue

            # 武器名称
            weapon_td = tds[1]
            weapon_link = weapon_td.find('a')
            weapon_name = weapon_link.get_text(strip=True) if weapon_link else weapon_td.get_text(strip=True)

            # 星级
            star_td = tds[2]
            star_text = star_td.get_text(strip=True)

            # 词条（从 data-param 属性获取）
            param3 = row.get('data-param3', '').strip()
            param4 = row.get('data-param4', '').strip()
            param5 = row.get('data-param5', '').strip()

            raw_new_data.append([weapon_name, star_text, param3, param4, param5])

        # ---------- 2. 过滤：只保留5/6星且三个词条齐全的武器 ----------
        filtered_new_data = []
        for item in raw_new_data:
            name, star, p3, p4, p5 = item
            if star not in ('5星', '6星'):
                continue
            if not (p3 and p4 and p5):  # 任一为空则跳过
                continue
            filtered_new_data.append(item)

        # ---------- 3. 读取现有 CSV（如果存在） ----------
        existing_rows = []  # 保持原始顺序的列表，每个元素是 [武器,星级,词条1,词条2,词条3]
        name_to_existing = {}  # 武器名 -> (索引, 数据列表) ，假设武器名唯一

        if os.path.isfile(csv_filename):
            with open(csv_filename, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.reader(f)
                headers = next(reader)  # 跳过表头
                for idx, row in enumerate(reader):
                    if len(row) >= 5:
                        name = row[0].strip()
                        data = [row[1].strip(), row[2].strip(), row[3].strip(), row[4].strip()]
                        existing_rows.append([name] + data)
                        name_to_existing[name] = (idx, [name] + data)  # 存储完整行以备后续比较

        # ---------- 4. 比较并分类：新增、修改 ----------
        new_additions = []  # 新增行（按解析顺序）
        modifications = []  # 修改行（按解析顺序）
        modified_names = set()  # 记录被修改的武器名，用于后续跳过

        for new_item in filtered_new_data:
            name, star, p3, p4, p5 = new_item
            if name in name_to_existing:
                # 已存在，比较字段
                old_full = name_to_existing[name][1]  # 完整旧行 [name, star, p3, p4, p5]
                old_data = old_full[1:]
                new_data = [star, p3, p4, p5]
                if new_data != old_data:
                    # 有更新
                    modifications.append(new_item)
                    modified_names.add(name)
            else:
                # 新增
                new_additions.append(new_item)

        # ---------- 5. 构建最终输出列表（按指定顺序） ----------
        final_rows = []
        # 5.1 新增行
        final_rows.extend(new_additions)
        # 5.2 修改行
        final_rows.extend(modifications)
        # 5.3 未变行（保持原有顺序，跳过被修改的）
        for row in existing_rows:
            if row[0] not in modified_names:
                final_rows.append(row)

        # ---------- 6. 写回 CSV ----------
        with open(csv_filename, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['武器', '星级', '毕业词条1', '毕业词条2', '毕业词条3'])
            writer.writerows(final_rows)

        # ---------- 7. 打印更新结果 ----------
        def format_item(item):
            name, star, p3, p4, p5 = item
            return f"{name}({star},{p3},{p4},{p5})"

        def format_item_log(action, items, color):
            log_lines = [f"已{action}："]
            log_lines.extend(format_item(it) for it in items)
            self.log_cb("\n".join(log_lines), color)

        if new_additions:
            format_item_log("新增", new_additions, "green")
        if modifications:
            format_item_log("修改", modifications, "gold")
        if not new_additions and not modifications:
            self.log_cb("武器数据已是最新，未进行更新", "gold")
        self.log_cb("[系统] 已完成武器列表更新", "blue")

    def __run__(self):
        cfg_update_weapon = self.dm.data.get("update_weapon", False)

        if cfg_update_weapon:
            self.log_cb("[系统] 开始更新武器列表...", "blue")
            response = requests.get(weapon_url, cookies=cookies, headers=headers)
            self.export_weapon_data(response)
