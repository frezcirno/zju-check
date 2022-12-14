import re
import json
import time
from typing import Optional
import requests
from datetime import datetime

headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36'
}
BASE_URL = "https://healthreport.zju.edu.cn/ncov/wap/default/index"
SUBMIT_URL = 'https://healthreport.zju.edu.cn/ncov/wap/default/save'
LOGIN_URL = "https://zjuam.zju.edu.cn/cas/login?service=http%3A%2F%2Fservice.zju.edu.cn%2F"
REDIRECT_URL = "https://zjuam.zju.edu.cn/cas/login?service=https%3A%2F%2Fhealthreport.zju.edu.cn%2Fa_zju%2Fapi%2Fsso%2Findex%3Fredirect%3Dhttps%253A%252F%252Fhealthreport.zju.edu.cn%252Fncov%252Fwap%252Fdefault%252Findex%26from%3Dwap"
SC_KEY = ""


def rsa_encrypt(password_str, e_str, M_str):
    password_bytes = bytes(password_str, 'ascii')
    password_int = int.from_bytes(password_bytes, 'big')
    e_int = int(e_str, 16)
    M_int = int(M_str, 16)
    result_int = pow(password_int, e_int, M_int)
    return hex(result_int)[2:].rjust(128, '0')


def login(username, password, sess: requests.Session):
    """ Login to ZJU platform """
    res = sess.get(LOGIN_URL, headers=headers)
    execution = re.search('name="execution" value="(.*?)"', res.text).group(1)
    res = sess.get('https://zjuam.zju.edu.cn/cas/v2/getPubKey', headers=headers).json()
    n, e = res['modulus'], res['exponent']
    encrypt_password = rsa_encrypt(password, e, n)

    data = {
        'username': username,
        'password': encrypt_password,
        'execution': execution,
        '_eventId': 'submit',
        "authcode": ""
    }
    res = sess.post(LOGIN_URL, data=data, headers=headers)
    # check if login successfully
    if "统一身份认证平台" in res.text:
        raise RuntimeError('登录失败，请核实账号密码重新登录')
    print("统一认证平台登录成功~")
    return sess


def get_geo_info(lnglat) -> dict:
    params = (
        ('key', '729923f88542d91590470f613adb27b5'),
        ('s', 'rsv3'),
        ('language', 'zh_cn'),
        ('location', f'{lnglat[0]},{lnglat[1]}'),
        ('extensions', 'base'),
        ('callback', 'jsonp_376062_'),
        ('platform', 'JS'),
        ('logversion', '2.0'),
        ('appname', 'https://healthreport.zju.edu.cn/ncov/wap/default/index'),
        ('csid', '63157A4E-D820-44E1-B032-A77418183A4C'),
        ('sdkversion', '1.4.19'),
    )

    response = requests.get('https://restapi.amap.com/v3/geocode/regeo', headers=headers, params=params)
    s = re.search("^jsonp_\d+_\((.*?)\);?$", response.text, re.S)
    return json.loads(s.group(1) if s else "{}")


def generate_form_param(geo_info: dict, campus: Optional[str], control_measures: Optional[str], sess: requests.Session):
    """ 构造表单参数 """
    res = sess.get(BASE_URL, headers=headers)
    if not res.ok:
        raise RuntimeError(f"Get base page failed {res.status_code} {res.reason}")

    html = res.text

    old_info = json.loads(re.findall(r'oldInfo: ?(\{[^\n]*\})', html)[0])
    if not old_info:
        raise RuntimeError("未发现缓存信息，请先至少手动成功打卡一次再运行脚本")

    def_info = json.loads(re.findall(r'def ?= ?(\{[^\n]*\})', html, re.S)[0])

    magic_code = re.findall(
        r'"([0-9a-z]{32})": "([0-9]{10})","([0-9a-z]{32})":"([0-9a-z]{32})"', html)[0]
    if len(magic_code) != 4:
        raise RuntimeError("未发现magic_code")

    magic_code_group = {
        magic_code[0]: magic_code[1],
        magic_code[2]: magic_code[3]
    }

    formatted_address = geo_info["regeocode"]["formatted_address"]
    address_component = geo_info["regeocode"]["addressComponent"]
    lng, lat = address_component["streetNumber"]["location"].split(",")
    province = address_component['province']
    city = address_component['city']
    district = address_component['district']

    geo_api_info_dict = {
        "type": "complete",
        "info": "SUCCESS",
        "status": 1,
        "position": {"Q": lat, "R": lng, "lng": lng, "lat": lat},
        "message": "Get ipLocation success.Get address success.", "location_type": "ip",
        "accuracy": 40,
        "isConverted": "true",
        "addressComponent": address_component,
        "formattedAddress": formatted_address,
        "roads": [],
        "crosses": [],
        "pois": []
    }

    info_arg = {
        "id": '',
        "uid": '',
        'created_uid': '0',
        'date': datetime.now().strftime("%Y%m%d"),
        'created': round(time.time()),
        'sfyxjzxgym': '',  # 是否愿意接种新冠疫苗
        'sfbyjzrq': '0',  # 是否不宜接种人群
        'jzxgymqk': '0',  # 接种新冠疫苗情况，1是已接种第一针，4是已接种第二针（已满6个月），5是已接种第二针（未满6个月），6是已接种第三针，3是未接种
    }

    info_arg.update(def_info)
    del info_arg['jrdqtlqk']  # removed

    info_arg.update({
        'sfqtyyqjwdg': '',  # 今日是否因发热外的其他原因请假未到岗（教职工）或未返校（学生）？
        'sffrqjwdg': '',  # 今日是否因发热请假未到岗（教职工）或未返校（学生）？
        'sfhsjc': '',  # Deprecated

        'zgfx14rfh': "0",  # Deprecated
        'zgfx14rfhdd': '',  # Deprecated
        'zgfx14rfhsj': '',  # Deprecated

        'sfcxtz': "0",  # Deprecated
        'sfyyjc': "0",  # Deprecated
        'jcjgqr': "0",  # Deprecated
        'jcjg': '',  # Deprecated

        'sfcxzysx': "1" if control_measures else "0",  # 是否有涉及涉疫情的管控措施
        'qksm': control_measures,  # 如有，情况说明 例如'处于防范区管控'
        'remark': '',  # 如有，情况说明

        'szgj': "",  # 所在国家，默认为中国
        'sfsfbh': '0',
        'jhfjrq': '',
        'jhfjjtgj': '',
        'jhfjhbcc': '',
        'jhfjsftjwh': '0',
        'jhfjsftjhb': '0',
        'szsqsfybl': '0',
        'gwszgz': '',
        'gwszgzcs': "",  # 所在城市
        'szgjcs': '',  # 所在国家 + 所在城市

        'address': formatted_address,  # 格式化地址
        # 地理位置
        'area': f"{province} {city} {district}",
        'province': province,  # 地理位置
        'city': city,  # 地理位置
        'geo_api_info': json.dumps(geo_api_info_dict, ensure_ascii=False, separators=(',', ':')),
        'sfzx': '1' if campus else '0',  # 是否在校
        'campus': campus,  # 所在校区
        'sfymqjczrj': "0",  # 是否存在发热症状、红黄码状态或者14天内从境外返校情况
        'sfjcwhry': "0",  # Deprecated
        'sfjchbry': "0",  # Deprecated

        'sfjcbh': "0",  # 是否有与新冠疫情确诊人员或密接人员有接触的情况
        'jcbhlx': '',  # 接触病患类型
        'jcbhrq': '',  # 接触病患人群

        'ismoved': "5",  # 2离省 3离市 4出境 5无
        'fxyy': '',
        'bztcyy': '',  # 不在同城原因
        'fjsj': '0',
        'sftjhb': "",  # 是否途径湖北
        'sftjwh': "0",  # 是否途径武汉

        'sfjcqz': "",  # 是否接触确诊
        'jcqzrq': '',  # 接触确诊人群

        'sfcyglq': "0",  # 今日是否居家隔离观察
        'gllx': '',  # 隔离类型
        'glksrq': '',  # 隔离开始日期

        'jrsfqzys': "",  # 今日是否确诊XX
        'jrsfqzfy': "",  # 今日是否确诊返阴

        'tw': '0',  # 是否发热
        'sfyqjzgc': "0",  # 是否到具有发热门诊（诊室）的医疗机构就诊？
        'jrdqjcqk': '',  # 今日定期检查情况？
        'jcwhryfs': '',
        'jchbryfs': '',

        'sfsqhzjkk': "0",  # 是否已经申领校区所在地健康码
        'sqhzjkkys': "1",  # 今日申领健康码的状态 1: '绿', 2: '红', 3: '黄', 4: '橙'
        'sfygtjzzfj': '0',
        'gtjzzfjsj': '',

        'zjdfgj': '',  # 近14日到访过的国家/地区

        'sfyrjjh': "0",  # 未来14天内是否有入境计划
        # 如有
        'cfgj': '',  # 国家或地区
        'tjgj': '',  # 途经国家
        'nrjrq': "0",  # 拟入境日期
        'rjka': '',  # 入境口岸
        'jnmddsheng': '',  # 境内目的地
        'jnmddshi': '',  # 境内目的地
        'jnmddqu': '',  # 境内目的地
        'jnmddxiangxi': '',  # 境内目的地
        'rjjtfs': '',  # 入境交通方式
        'rjjtfs1': '',  # 其他入境交通方式
        'rjjtgjbc': '',  # 入境交通工具
        'jnjtfs': '',  # 境内交通方式
        'jnjtfs1': '',  # 其他境内交通方式
        'jnjtgjbc': '',  # 境内交通工具

        # new
        'internship': "1",  # 实习情况 "1": '否', "2": '校内', "3": "校外"
        'gwszdd': '',
        'xjzd': "",
        'sfqrxxss': "1",  # 是否确认信息属实
        'verifyCode': '',
    })
    info_arg.update(magic_code_group)

    if len(info_arg) != 90:
        raise RuntimeError("打卡问卷可能更新，请检查并更新代码")

    return info_arg


def check_in(username, password, lnglat, campus, control_measures, sess=requests.Session()):
    """ """
    login(username, password, sess)

    res = sess.get(REDIRECT_URL)
    if not res.ok:
        raise RuntimeError(f"Redirect failed {res.status_code} {res.reason}")

    geo_info = get_geo_info(lnglat)
    if 'regeocode' not in geo_info:
        raise RuntimeError("获取地理位置信息失败")

    data = generate_form_param(geo_info, campus, control_measures, sess)

    response = sess.post(SUBMIT_URL, data=data, headers=headers)

    return response.json()


def push(title: str, desp: str) -> bool:
    data = {
        'title': title,
        'desp': desp
    }
    res = requests.post(f'https://sctapi.ftqq.com/{SC_KEY}.send', data=data)
    if not (res.json().get("errmsg") == "success"):
        print(res.json())
    return res.json().get("errmsg") == "success"


if not SC_KEY:
    push = print

if __name__ == "__main__":
    student_id = ''
    password = ''
    lnglat = (121.63529, 29.89154)  # 宁波
    campus = "宁波校区"
    control_measures = ""

    try:
        res = check_in(student_id, password, lnglat, campus, control_measures)
        if '今天已经填报了' in res['m']:
            push("【浙大健康打卡】今日已打卡", f"今日已打卡, 返回消息为: {res}")
        else:
            push("【浙大健康打卡】打卡成功", f"打卡成功, 返回消息为: {res}")

    except Exception as e:
        push("【浙大健康打卡】打卡失败", f"打卡失败, 原因为: {e}")
