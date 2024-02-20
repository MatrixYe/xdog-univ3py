# -*- coding: utf-8 -*-#
# -------------------------------------------------------------------------------
# Name:         a 
# Author:       yepeng
# Date:         2021/10/22 2:44 下午
# Description: 
# -------------------------------------------------------------------------------
import logging

from pymongo import MongoClient
from redis import StrictRedis
from web3 import Web3, HTTPProvider
from web3.contract import Contract

from config import load_config, Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
lg = logging.getLogger(__name__)

BASE = "univ3_base"
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
        pass

    # 核心逻辑
    def _loop(self):
        block_height = self.w3.eth.get_block_number()
        print(f"block height is {block_height}")


if __name__ == '__main__':
    print("hello world")
    Task().run()
