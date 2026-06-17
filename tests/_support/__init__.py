"""测试支持模块（非测试文件，供 import-path 引用）。

供集成测试经 ``"tests._support.edge_ext:SampleEdgeExt"`` 这类 import-path 引用，
以验证 ``MCSConfig.from_file`` + ``Phase1Builder`` 的 import-path 解析在真实 build 流程中可用。
"""
