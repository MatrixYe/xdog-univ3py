# -*- coding: utf-8 -*-#
# -------------------------------------------------------------------------------
# Name:         a 
# Author:       yepeng
# Date:         2021/10/22 2:44 下午
# Description: 
# -------------------------------------------------------------------------------
import json
import logging
import time
from typing import Any

from eth_abi import abi
from pymongo import MongoClient
from redis import StrictRedis
from web3 import Web3, HTTPProvider
from web3.contract import Contract

from config import load_config, Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
lg = logging.getLogger(__name__)

UNIV3_BASE = "univ3_base"
TOKENS = "tokens"
UNIV3_PAIRS = "univ3_pairs"
UNIV3_EVENT = "univ3_event"
UNIV3_SWAP = "univ3_swap"
UNIV3_RAT = "univ3_rat"
UNIV3_KLINE = "univ3_kline"


class Task:
    """

    """

    def __init__(self):
        self.conf: Config = self._load_config()  # 加载配置文件
        self._factory_abi = self._read_factory_abi()  # 读取factory合约abi
        self._pair_abi = self._read_pair_abi()  # 读取pool合约abi
        self._erc20_abi = self._read_erc20_abi()  # 读取erc20合约abi

        self.db = self._connect_mongo()  # 连接mongodb
        self.rs = self._connect_redis()  # 连接redis
        self.w3 = self._connect_eth_client()  # 连接以太坊节点
        self.factory_instance = self._gen_factory_instance(self.conf.factory)  # 构建factory合约实例

    # 加载配置文件
    @staticmethod
    def _load_config(conf_file="./config.toml") -> Config:
        c = load_config(file_path=conf_file)
        lg.info(c.format_json())
        return c

    # 读取factory 合约abi
    @staticmethod
    def _read_factory_abi():
        with open('./source/abi/UniswapV3Factory.abi', 'r') as f:
            return f.read()

    # 读取pool 合约 abi
    @staticmethod
    def _read_pair_abi():
        with open('./source/abi/UniswapV3Pool.abi', 'r') as f:
            return f.read()

    # 读取erc20 合约 abi
    @staticmethod
    def _read_erc20_abi():
        with open('./source/abi/ERC20.abi', 'r') as f:
            return f.read()

    @staticmethod
    def _parse_com(log):
        address = log.get('address')
        # block_hash = log.get('blockHash')
        block_number = log.get('blockNumber')
        log_index = log.get('logIndex')
        topics = log.get('topics')
        tx_hash = log.get('transactionHash')
        tx_index = log.get('transactionIndex')
        return {
            '_id': f"N{block_number}I{log_index}",
            'address': address.lower(),
            'block_number': block_number,
            # 'block_hash': block_hash.hex().lower(),# 废弃字段
            'log_index': log_index,
            'tx_hash': tx_hash.hex().lower(),
            'tx_index': tx_index,
            'topic0': [a.hex() for a in topics]
        }

    # 连接 redis数据库
    def _connect_redis(self) -> StrictRedis:
        lg.info("_connect_eth_client... ...")
        host = self.conf.redis.host
        port = self.conf.redis.port
        password = self.conf.redis.password
        db = self.conf.redis.db
        redis_client = StrictRedis(host=host, port=port, password=password, db=db, decode_responses=True)
        return redis_client

    # 获取数据库，根据网络名称命名，如ethereum，这样可支持多链数据同步
    # 连接mongodb 数据库
    def _connect_mongo(self):
        lg.info(f"_connect_mongo ... ...")
        host = self.conf.mongo.host
        port = self.conf.mongo.port
        username = self.conf.mongo.username
        password = self.conf.mongo.password
        client = MongoClient(host=host, port=port, username=username, password=password)
        return client[self.conf.network]

    # 连接以太坊节点
    def _connect_eth_client(self) -> Web3:
        lg.info(f"_connect_eth_client ... ...")
        return Web3(HTTPProvider(endpoint_uri=self.conf.node_url))

    # 构建factory实例
    def _gen_factory_instance(self, factory_address: str) -> Contract:
        contract_address = self.w3.to_checksum_address(factory_address)
        return self.w3.eth.contract(address=contract_address, abi=self._factory_abi)

    # 核心功能代码入口
    def run(self):
        self._initialize()
        self._loop()

    # 初始化操作
    def _initialize(self):
        lg.info("to initialize... ...")
        result = self._get_base()
        if not result:
            data = {
                '_id': 1,
                'start_block': self.conf.start_block,
                'sync_block': self.conf.start_block,
                'config': self.conf.to_json(),
            }
            self.db[UNIV3_BASE].insert_one(data)
        else:
            self.db[UNIV3_BASE].update_one({'_id': 1}, {'$set': {'config': self.conf.to_json()}})
            lg.info(f"base:{result}")

        # event 索引
        # self.db[UNIV3_EVENT].create_index([('ts', 1)])
        # self.db[UNIV3_EVENT].create_index([('name', 1)])
        # pair索引
        self.db[UNIV3_PAIRS].create_index([('create_time', 1)])
        self.db[UNIV3_PAIRS].create_index([('coin_addr', 1)])
        # swap 集合索引
        self.db[UNIV3_SWAP].create_index([("ts", 1)])
        self.db[UNIV3_SWAP].create_index([("block_number", 1)])
        self.db[UNIV3_SWAP].create_index([("pair", 1), ("ts", 1)])
        self.db[UNIV3_SWAP].create_index([("trader", 1), ("ts", 1)])
        # 老鼠仓 索引
        # self.db[UNIV3_RAT].create_index([("pair", 1)])
        # self.db[UNIV3_RAT].create_index([("ts", 1)])
        # K线索引,时间戳和pair联合唯一索引
        # self.db[UNIV3_KLINE].create_index([('pair', 1), ('start_time', 1)], unique=True)

    # 核心逻辑
    def _loop(self):
        skip_flag = self.conf.skip_history  # 标识，是否跳过历史数据，从当前块开始同步
        start_height = self._get_sync_block()  # 本地历史高度
        if skip_flag or not start_height:
            # 从当前高度开始同步
            lg.info("skip_history is true --> sync by current block height")
            lg.info(
                f"skik_history:{skip_flag} -> f{'sync by current remote height' if skip_flag else 'sync by history height'}")
            lg.info(f"default_start_height:{start_height}")
            remote_height = self._get_remote_block_number()

            if remote_height == 0:
                lg.warning("_get_remote_block_number = 0  --> exit")
                exit()
            self._set_sync_block(remote_height)

        while True:
            time.sleep(self.conf.sync_interval)
            x = self._get_sync_block()
            y = self._get_remote_block_number()
            lg.info(f"loop sync local block:{x} remote block:{y}")
            if y == 0:
                lg.error("_loop:failed to get remote block!")
                continue
            if x == 0:
                lg.error("_loop:failed to get history block!")
                continue
            if x > y:
                lg.warning("_loop:local block > remote block")
                continue
            if x == y:
                continue

            self._update_base("remote_block", y)
            for i in range(x + 1, y + 1):
                lg.debug(f"_loop:to scan block {i}")
                self._to_scan_block(i)
                self._set_sync_block(i)
                time.sleep(0.2)

    def _to_scan_block(self, i: int):
        lg.info(f'to scan block:{i}')
        block = self.w3.eth.get_block(i)
        ts = block['timestamp']
        logs = self.w3.eth.get_logs(filter_params={
            'fromBlock': i,
            'toBlock': i,
        })
        for log in logs:
            tx_hash = log.get("transactionHash").hex()
            contract_addr = log.get('address').lower()
            # 优先判断是否来自factory的event
            if contract_addr == self.conf.factory.lower():
                tx = self._fetch_tx(tx_hash)
                if not tx:
                    continue
                self._handle_factory_event(ts, tx, log)
                continue
                # 判断是否来自pair的event
            pair_obj = self._get_pair(contract_addr)
            if pair_obj:
                tx = self._fetch_tx(tx_hash)
                if not tx:
                    continue
                self._handle_pair_event(ts, tx, log, pair_obj)
                continue

    # 获取tx数据，从本地缓存先取，取不到从链上取
    def _fetch_tx(self, tx_hash) -> dict | None:
        # tx_cache = self.rs.get(tx_hash)
        tx_cache = self.rs.get(tx_hash)
        if tx_cache:
            # lg.info(f"cache is exist:{tx_hash}")
            return json.loads(tx_cache)
        else:
            tx = self._get_remote_tx(tx_hash)
            if not tx:
                return None
            data = {
                'tx_hash': tx_hash.lower(),
                'from': tx['from'].lower(),
                'nonce': tx['nonce']
            }
            self.rs.set(tx_hash, json.dumps(data), 120)  # 默认保存2分钟的哈希数据
            return data

    # 获取远程tx数据
    def _get_remote_tx(self, tx_hash):
        try:
            tx = self.w3.eth.get_transaction(tx_hash)
            return tx
        except Exception as e:
            lg.error(f"_get_remote_tx:{e}")
            return None

    # 获取同步器状态数据
    def _get_base(self):
        return self.db[UNIV3_BASE].find_one({'_id': 1})

    # 获取本地同步sync高度
    def _get_sync_block(self) -> int:
        base = self._get_base()
        return base.get('sync_block')

    # 获取远程block高度
    def _get_remote_block_number(self) -> int:
        try:
            num = self.w3.eth.block_number
            return num
        except Exception as e:
            lg.error(f"_get_remote_block_number:{e}")
            return 0

    # 设置最新同步高度到本地
    def _set_sync_block(self, height: int):
        self._update_base('sync_block', height)
        lg.info(f"_set_sync_block:{height}")

    # 更新同步器状态
    def _update_base(self, field: str, new_data: Any):
        self.db[UNIV3_BASE].update_one({'_id': 1}, {'$set': {field: new_data}})

    # 处理factory的合约event
    def _handle_factory_event(self, ts: int, tx: dict, log):
        topics = log.get('topics')
        if not topics:
            return
        match topics[0].hex().lower():
            # todo 需要补充event topic
            case '':
                event_name = "PairCreated"
                lg.info(f"find event Factoy:{event_name}")
                self._handle_factory_event_paircreated(ts, tx, log, event_name)

    # 处理pair合约的event
    def _handle_pair_event(self, ts: int, tx: dict, log, pair_obj):
        topics = log.get('topics')
        if not topics:
            return
        match topics[0].hex().lower():
            # todo 补充topic
            case '':
                event_name = "Swap"
                # lg.info(f"find event Pair:{event_name}")
                self._handle_pair_event_swap(ts, tx, log, pair_obj, event_name)
            case _:
                pass

    # 从数据库中查找pair对象by地址
    def _get_pair(self, addr: str):
        return self.db[UNIV3_PAIRS].find_one({'_id': addr.lower()})

    def _handle_factory_event_paircreated(self, ts: int, tx: dict, log, event_name):
        # todo 补充逻辑
        pass

    def _handle_pair_event_swap(self, ts, tx, log, pair_obj, event_name):
        # todo 修改方名和解析数据
        # ndex_topic_1 address sender, uint256 amount0In, uint256 amount1In, uint256 amount0Out, uint256 amount1Out, index_topic_2 address to
        event = self._parse_com(log)
        topics = log.get("topics")
        sender = abi.decode(['address'], topics[1])[0]
        s_to = abi.decode(['address'], topics[2])[0]
        # s_to = topics[2].hex().replace("000000000000000000000000", "")
        arg_types = ['uint256', 'uint256', 'uint256', 'uint256']
        data = log.get('data')
        (amount0in, amount1in, amount0out, amount1out) = abi.decode(arg_types, data)
        event['from'] = tx['from']
        event['nonce'] = tx['nonce']
        event['name'] = event_name
        event['ts'] = ts
        entity = {
            'sender': sender,
            'amount0in': str(amount0in),
            'amount1in': str(amount1in),
            'amount0out': str(amount0out),
            'amount1out': str(amount1out),
            'to': s_to
        }

        event['entity'] = entity


if __name__ == '__main__':
    print("hello world")
    Task().run()
