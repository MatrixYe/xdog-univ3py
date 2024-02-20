# -*- coding: utf-8 -*-#
# -------------------------------------------------------------------------------
# Name:         a 
# Author:       yepeng
# Date:         2021/10/22 2:44 下午
# Description: 
# -------------------------------------------------------------------------------
import re
import time

import requests
from pymongo import MongoClient
from redis import StrictRedis


def contains_ethereum_address(text):
    # 匹配以太坊地址的正则表达式
    pattern = re.compile(r'0x[a-fA-F0-9]{40}')

    # 使用正则表达式进行匹配
    ads = re.findall(pattern, text)

    return ads


# 连接mongodb数据库
def connect_mongo(host: str, port: int, username: str, password: str):
    client = MongoClient(host=host, port=port, username=username, password=password)
    return client


# 连接redis数据库
def connect_redis(host: str, port: int, password: str, db=0):
    redis_client = StrictRedis(host=host, port=port, password=password, db=db, decode_responses=True)
    return redis_client


# 通过飞书bot发送消息到飞书群
def send_feishu(url: str, msg: str):
    # url = "https://open.feishu.cn/open-apis/bot/v2/hook/e9078a15-fac0-4957-a76d-cdd2c309a812"
    # msg = "hello,i'm a bot,this is a test message. "
    text = {
        "msg_type": "text",
        "content":
            {
                "text": msg
            }
    }
    requests.post(url=url, json=text)


def now_date(format_str="%Y%m%d", delay=0):
    t = time.localtime(time.time() - delay)
    date = time.strftime(format_str, t)
    return date
