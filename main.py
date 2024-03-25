# -*- coding: utf-8 -*-#
# -------------------------------------------------------------------------------
# Name:         a 
# Author:       yepeng
# Date:         2021/10/22 2:44 下午
# Description: 
# -------------------------------------------------------------------------------
import argparse
import json
import logging
import time
from typing import Any

from eth_abi import abi
from pymongo import MongoClient
from redis import StrictRedis
from web3 import Web3, HTTPProvider
from web3.contract import Contract
from web3.types import BlockData

from config import load_config, Config

parser = argparse.ArgumentParser()

parser.add_argument("--config", "-c", type=str)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
lg = logging.getLogger(__name__)

UNIV3_BASE = "univ3_base"
TOKENS = "tokens"
UNIV3_POOLS = "univ3_pools"
UNIV3_EVENT = "univ3_event"
UNIV3_SWAP = "univ3_swap"
UNIV3_RAT = "univ3_rat"
UNIV3_KLINE = "univ3_kline"


class Task:
    """

    """

    def __init__(self, config_path: str):
        self.conf: Config = self._load_config(config_path)  # 加载配置文件
        self._factory_abi = self._read_factory_abi()  # 读取factory合约abi
        self._pool_abi = self._read_pool_abi()  # 读取pool合约abi
        self._erc20_abi = self._read_erc20_abi()  # 读取erc20合约abi

        self.db = self._connect_mongo()  # 连接mongodb
        self.rs = self._connect_redis()  # 连接redis
        self.w3 = self._connect_eth_client()  # 连接以太坊节点
        # self.factory_instance = self._gen_factory_instance(self.conf.factory)  # 构建factory合约实例,废弃，不调方法，无需使用

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
    def _read_pool_abi():
        with open('./source/abi/UniswapV3Pool.abi', 'r') as f:
            return f.read()

    # 读取erc20 合约 abi
    @staticmethod
    def _read_erc20_abi():
        with open('./source/abi/ERC20.abi', 'r') as f:
            return f.read()

    @staticmethod
    def _parse_com(log) -> dict:
        address = log.get('address')
        # block_hash = log.get('blockHash')
        block_number = log.get('blockNumber')
        log_index = log.get('logIndex')
        topics = log.get('topics')
        tx_hash = log.get('transactionHash')
        tx_index = log.get('transactionIndex')
        return {
            # '_id': f"N{block_number}I{log_index}",# 废弃
            'address': address.lower(),
            'block_number': block_number,
            # 'block_hash': block_hash.hex().lower(),# 废弃字段
            'log_index': log_index,
            'tx_hash': tx_hash.hex().lower(),
            'tx_index': tx_index,
            'topics': [a.hex() for a in topics]
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

    # 构建pool实例
    def _gen_pool_instance(self, pool_address: str) -> Contract:
        contract_address = self.w3.to_checksum_address(pool_address)
        return self.w3.eth.contract(address=contract_address, abi=self._pool_abi)

    # 构建erc20 tolen 实例
    def _gen_erc20_instance(self, erc20_address: str) -> Contract:
        contract_address = self.w3.to_checksum_address(erc20_address)
        return self.w3.eth.contract(address=contract_address, abi=self._erc20_abi)

    # 核心功能代码入口
    def run(self):
        self._initialize()
        self._loop()

    def test(self, height: int):
        self._initialize()
        self._to_scan_block(height)

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
        # pool索引
        self.db[UNIV3_POOLS].create_index([('create_time', 1)])
        self.db[UNIV3_POOLS].create_index([('coin_addr', 1)])
        # swap 集合索引
        # self.db[UNIV3_SWAP].create_index([("ts", 1)])
        # self.db[UNIV3_SWAP].create_index([("block_number", 1)])
        # self.db[UNIV3_SWAP].create_index([("pool", 1), ("ts", 1)])
        # self.db[UNIV3_SWAP].create_index([("trader", 1), ("ts", 1)])
        # 老鼠仓 索引
        # self.db[UNIV3_RAT].create_index([("pool", 1)])
        # self.db[UNIV3_RAT].create_index([("ts", 1)])
        # K线索引,时间戳和pool联合唯一索引
        # self.db[UNIV3_KLINE].create_index([('pool', 1), ('start_time', 1)], unique=True)

    # 核心逻辑
    def _loop(self):
        skip_flag = self.conf.skip_history  # 标识，是否跳过历史数据，从当前块开始同步
        start_height = self._get_sync_block()  # 本地历史高度
        lg.info(f"skik_history:{skip_flag},local history sync height:{start_height}")
        # 当设置跳过历史数据，或者从本地获取历史高度数据为0时，直接从当前链上高度开始同步，并设置历史高度为当前远程高度
        if skip_flag or not start_height:
            lg.info(f"skik_history is true or local history sync is 0 -> sync by current remote height")
            remote_height = self._get_remote_block_number()
            lg.info(f"get remote height:{remote_height}")
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
                lg.error("_loop:failed to get remote block! -> pass")
                continue
            if x == 0:
                lg.error("_loop:failed to get history block! -> pass")
                continue
            if x > y:
                lg.warning("_loop:local block > remote block -> pass")
                continue
            if x == y:
                # lg.debug("_loop:local block = remote block -> pass")
                continue

            self._update_base("remote_block", y)
            # scan block x < h < y+1
            for i in range(x + 1, y + 1):
                lg.debug(f"_loop:to scan block {i}")
                ok = self._to_scan_block(i)
                if not ok:
                    break
                self._set_sync_block(i)
                time.sleep(0.2)

    def _get_block(self, i: int) -> BlockData | None:
        try:
            return self.w3.eth.get_block(i)
        except Exception as e:
            lg.error(e)
            return None

    def _to_scan_block(self, i: int) -> bool:
        lg.info(f'to scan block:{i}')
        block = self._get_block(i)
        if block is None:
            return False
        ts = block['timestamp']
        logs = self.w3.eth.get_logs(filter_params={
            'fromBlock': i,
            'toBlock': i,
        })
        for log in logs:
            tx_hash = log.get("transactionHash").hex()
            contract_addr = log.get('address').lower()  # 发送event的合约地址
            # 优先判断是否来自factory的event
            if contract_addr == self.conf.factory.lower():
                tx = self._fetch_tx(tx_hash)
                if not tx:
                    continue
                self._handle_factory_event(ts, tx, log)
                continue
            # 判断是否来自pool的event 暂时不开启
            # pool_obj = self._get_pool(contract_addr)
            # if pool_obj:
            #     tx = self._fetch_tx(tx_hash)
            #     if not tx:
            #         continue
            #     self._handle_pool_event(ts, tx, log, pool_obj)
            #     continue
        return True

    # 获取tx数据，从本地缓存先取，取不到从链上取
    # noinspection PyTypeChecker
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
            self.rs.set(tx_hash, json.dumps(data), 300)  # 默认保存2分钟的哈希数据
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
            # event PoolCreated topic
            case '0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118':
                event_name = "PoolCreated"
                lg.info(f"find event:UniswapV3Factory|{event_name}")
                self._handle_factory_event_poolcreated(ts, tx, log, event_name)

    # 处理pool合约的event
    def _handle_pool_event(self, ts: int, tx: dict, log, pool_obj):
        topics = log.get('topics')
        if not topics:
            return
        match topics[0].hex().lower():
            # todo 补充topic
            case '':
                event_name = "Swap"
                lg.info(f"find event UniswapV3Pool:{event_name}")
                self._handle_pool_event_swap(ts, tx, log, pool_obj, event_name)
            case _:
                pass

    # 从数据库中查找pool对象by地址
    def _get_pool(self, addr: str):
        return self.db[UNIV3_POOLS].find_one({'_id': addr.lower()})

    # 处理factory合约event
    def _handle_factory_event_poolcreated(self, ts: int, tx: dict, log, event_name):
        #     event PoolCreated(
        #         address indexed token0,
        #         address indexed token1,
        #         uint24 indexed fee,
        #         int24 tickSpacing,
        #         address pool
        #     );
        event = self._parse_com(log)
        arg_types = ['int24', 'address']
        data = log.get('data')
        topics = log.get("topics")

        token0 = abi.decode(['address'], topics[1])[0]
        token1 = abi.decode(['address'], topics[2])[0]
        fee = abi.decode(['uint24'], topics[3])[0]

        (tickSpacing, pool) = abi.decode(arg_types, data)
        entity = {
            'token0': token0.lower(),
            'token1': token1.lower(),
            'fee': fee,
            'tickSpacing': tickSpacing,
            'pool': pool}
        event['entity'] = entity
        event['name'] = event_name

        # 忽略锚定币非weth的交易池
        if self.conf.weth not in [token0.lower(), token1.lower()]:
            # 0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2 WETH
            lg.warning(f"Not a Standard Pool:{pool} {token0} {token1}")
            return

        # 获取token0的基本信息，非标准币不处理
        t0_info = self._fetch_erc20(token0)
        if not t0_info:
            lg.warning(f"can not up new pool,token-0 not erc20:{token0}")
            return
        # 获取token1的基本信息，非标准币不处理
        t1_info = self._fetch_erc20(token1)
        if not t1_info:
            lg.warning(f"can not up new pool,token-1 not erc20:{token1}")
            return

        t0_address = t0_info['address']
        t1_address = t1_info['address']

        t0_symbol = t0_info['symbol']
        t1_symbol = t1_info['symbol']

        t0_decimal = t0_info['decimal']
        t1_decimal = t1_info['decimal']

        t0_total_supply = t0_info['total_supply']
        t1_total_supply = t1_info['total_supply']

        # 标准化，分类pool，计算锚定币种的位置
        stable_index = self._cal_stable_index(t0_address, t1_address)

        # 插入新池子数据
        new_pool_data = {
            '_id': pool.lower(),
            'pool': pool.lower(),
            # 'pindex': pindex,
            'name': f"{t0_symbol}/{t1_symbol}" if stable_index == 1 else f"{t1_symbol}/{t0_symbol}",
            'coin_addr': t0_address if stable_index == 1 else t1_address,
            'coin_symbol': t0_symbol if stable_index == 1 else t1_symbol,
            'coin_decimal': t0_decimal if stable_index == 1 else t1_decimal,
            'coin_total_supply': t0_total_supply if stable_index == 1 else t1_total_supply,
            'stable_addr': t0_address if stable_index == 0 else t1_address,
            'stable_symbol': t0_symbol if stable_index == 0 else t1_symbol,
            'stable_decimal': t0_decimal if stable_index == 0 else t1_decimal,
            'stable_index': stable_index,
            'create_time': ts,
            'create_block': event['block_number'],
            'create_tx': tx['tx_hash'],
            'creator': tx['from'],
            'fee': fee,
            'tickSpacing': tickSpacing,
            'event': event
        }
        lg.info(f"save new pool:{pool.lower()}")
        self._find_and_set(UNIV3_POOLS, {'_id': pool.lower()}, new_pool_data, upsert=True)
        # todo 往redis中推送新池子创建信息

    # 处理event：PoolCreated
    def _handle_pool_event_swap(self, ts, tx, log, pool_obj, event_name):
        # todo 修改方名和解析数据
        #     event Swap(
        #         address indexed sender,
        #         address indexed recipient,
        #         int256 amount0,
        #         int256 amount1,
        #         uint160 sqrtPriceX96,
        #         uint128 liquidity,
        #         int24 tick
        #     );
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

    # 获取本地token相关信息
    def _get_local_erc20(self, addr: str) -> dict | None:
        token = self.db[TOKENS].find_one(filter={'_id': addr.lower()})
        return {
            'address': token.get('address'),
            'symbol': token.get('symbol'),
            'decimal': token.get('decimal'),
            'total_supply': token.get('total_supply')
        } if token else None

    # 从链上获取erc20信息
    def _get_remote_erc20(self, addr: str) -> dict | None:
        try:
            erc20_instance = self._gen_erc20_instance(addr)
            symbol = getattr(erc20_instance.functions, "symbol")().call()
            decimal = getattr(erc20_instance.functions, "decimals")().call()
            total_supply = getattr(erc20_instance.functions, "totalSupply")().call()
            return {
                'address': addr.lower(),
                'symbol': symbol,
                'decimal': decimal,
                'total_supply': total_supply / 10 ** decimal
            }
        except Exception as e:
            lg.error(f"_get_remote_erc20:{e}")
            return None

    # 获取erc20 token by local or remote
    def _fetch_erc20(self, addr: str) -> dict | None:
        ltoken = self._get_local_erc20(addr)  # 优先从本地获取
        if ltoken:
            # lg.info(f"token is exist {ltoken['symbol']}")
            return ltoken
        else:
            lg.info(f"token is not in local:{addr}")
            rtoken = self._get_remote_erc20(addr)
            self._to_save_erc20(rtoken)
            return rtoken

    # 保存erc20 token到本地
    def _to_save_erc20(self, rtoken: dict):
        if not rtoken:
            return
        lg.info(f'save erc20 token:{rtoken["symbol"]}')
        data = {
            '_id': rtoken['address'].lower(),
            'type': 'erc20',
            'address': rtoken['address'].lower(),
            'symbol': rtoken['symbol'],
            'decimal': rtoken['decimal'],
            'total_supply': rtoken['total_supply']
        }
        self._insert_docm(TOKENS, data)

    # 插入新文档到集合中
    def _insert_docm(self, coll: str, data):
        try:
            self.db[coll].insert_one(data)
        except Exception as e:
            lg.error(f"_insert_docm:{coll} {e}")

    def _cal_stable_index(self, t0: str, t1: str) -> int:
        """
        
        :param t0: 
        :param t1: 
        :return: 0:锚定币为t0，1:锚定币为t1，-1:未发现锚定币
        """
        w = self.conf.weth.lower()
        if w == t0.lower():
            return 0
        if w == t1.lower():
            return 1
        return -1

    # 找到文档，插入或者更新
    def _find_and_set(self, coll: str, query: dict, new_data: dict, upsert: bool):
        try:
            self.db[coll].find_one_and_update(filter=query, update={'$set': new_data}, upsert=upsert)
        except Exception as e:
            lg.error(f"_find_and_set:{new_data} {e}")


if __name__ == '__main__':
    lg.info("start to sync uniswap v3,good luck ... ...")
    args = parser.parse_args()
    cpath: str = args.config
    if not cpath:
        lg.error("pleace input config path,eg:'python mian.py -c config.toml' ")
        exit(500)
    print(cpath)
    task = Task(cpath)
    task.run()
