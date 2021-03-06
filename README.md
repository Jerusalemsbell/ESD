# ESD(Enumeration Sub Domain)
[![asciicast](https://asciinema.org/a/15WhUe40eEhSbwAXZdf2RQdq9.png)](https://asciinema.org/a/15WhUe40eEhSbwAXZdf2RQdq9)

## 优势
#### 支持泛解析域名
> 基于独创的`RSC`（响应相似度对比）技术对泛解析域名进行枚举（受网络质量、网站带宽等影响，速度会比较慢，单个域名在一小时以内）

基于`aioHTTP`获取一个不存在子域名的响应内容，并将其和字典子域名响应进行相似度比对。
超过阈值则说明是同个页面，否则则为可用子域名，并对最终子域名再次进行响应相似度对比。

#### 更快的速度
> 基于`AsyncIO`异步协程技术对域名进行枚举（受网络和DNS服务器影响会导致扫描速度小幅波动，基本在250秒以内）

基于`AsyncIO`+`aioDNS`将比传统多进程/多线程/gevent模式快50%以上。
通过扫描`qq.com`，共`170083`条规则，找到`1913`个域名，耗时`163`秒左右，平均`1000+条/秒`。

#### 更全的字典
> 融合各类字典，去重后共170083条子域名字典

- 通用字典
    - 单字母、单字母+单数字、双字母、双字母+单数字、双字母+双数字、三字母
    - 单数字、双数字、三数字
- 域名解析商公布使用最多的子域名
    - DNSPod: dnspod-top2000-sub-domains.txt
- 其它域名爆破工具字典
    - subbrute: names_small.txt
    - subDomainsBrute: subnames_full.txt

#### DNS服务器
- 解决各家DNS服务商对于网络线路出口判定不一致问题
- 解决各家DNS服务商缓存时间不一致问题

## 使用
仅在Python3下验证过
```
# 安装依赖
pip install -r requirements.txt

# 扫描单个域名
python ESD.py qq.com

# 扫描多个域名（英文逗号分隔）
python ESD.py qq.com,tencent.com

# 扫描文件（文件中每行一个域名）
python ESD.py targets.txt
```

## 后续
- 提升扫描速度
- 支持三级子域名，多种组合更多可能性

## 参考
- http://feei.cn/esd
- https://github.com/aboul3la/Sublist3r
- https://github.com/TheRook/subbrute
- https://github.com/lijiejie/subDomainsBrute
