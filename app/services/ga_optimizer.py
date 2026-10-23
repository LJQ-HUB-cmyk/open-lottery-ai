# -*- coding: utf-8 -*-
"""
遗传算法（GA）号码池优化器

整合策略：
  不独立运行"正向"或"反向"模式，而是把两者融合在一个 GA 进化过程里：
  - 频率分数表提供搜索空间和适应度基础项
  - 初始种群 70% 来自热号池 / 30% 来自冷门池（候选空间覆盖两端）
  - 变异算子 80% 常规 + 20% 反向冷门变异
  - 档位独立进化（每个档位跑一套种群）

核心流程：
  初始化种群 → 适应度评估 → 选择 → 交叉 → 变异 → 精英保留 → 迭代 → 输出最优
"""
import logging
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============ GA 超参数（可按需调） ============
GA_POP_SIZE = 50           # 种群大小（档位多，平衡速度）
GA_GENERATIONS = 80        # 迭代代数（种群 50×80=4000 评估，收敛足够）
GA_TOURNAMENT_SIZE = 3     # 锦标赛选择规模
GA_CROSSOVER_RATE = 0.8    # 交叉概率
GA_MUTATION_RATE = 0.1     # 变异概率
GA_ELITE_COUNT = 3         # 精英保留数量
GA_HOT_RATIO = 0.7         # 初始种群热号占比（反向占比 = 1 - 这个）
GA_REVERSE_MUTATION_RATE = 0.2  # 变异时走反向冷门的概率


# ============ 适应度权重 ============
W_FREQ = 0.35         # 频率加权和
W_COVERAGE = 0.25     # 区间覆盖度 + 奇偶均衡
W_HIST = 0.25         # 近30期回测表现
W_OVERLAP = 0.10      # 与已优化档位的号码重合惩罚（档位间差异化）
W_COST = 0.05         # 注数爆炸软惩罚

HIST_EVAL_PERIODS = 30   # 回测期数


# ============ 编码 ============

@dataclass
class Chromosome:
    """
    一条染色体 = 一个候选复试号码池。
    red_genes / blue_genes 都是唯一号码集合（不允许重复）。
    """
    red_genes: List[int]
    blue_genes: List[int]
    fitness: float = 0.0

    def key(self) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
        return (tuple(sorted(self.red_genes)), tuple(sorted(self.blue_genes)))


@dataclass
class GAConfig:
    """GA 运行时配置（从外部传进来）"""
    # 彩种
    lottery_type: str                 # "ssq" | "dlt"
    # 号码约束
    red_max: int                      # 红球最大号 33 / 35
    blue_max: int                     # 蓝球最大号 16 / 12
    pick_red: int                     # 投注红球 6 / 5
    pick_blue: int                    # 投注蓝球 1 / 2
    ball_unit: int                    # 每注金额(元)，双色球/大乐透均为 2
    # 候选池（已经过频率排序）
    red_freq_scores: Dict[int, float]  # 号码 → 频率分（越大越热）
    blue_freq_scores: Dict[int, float]
    # 当前目标档位
    red_pool_size: int
    blue_pool_size: int
    # 可选（有默认值）
    history_draws: List[Dict] = field(default_factory=list)   # 历史开奖回测样本
    optimized_pools: Optional[List[Dict]] = None              # 已优化档位的号码池，差异化惩罚用
    pop_size: int = GA_POP_SIZE
    generations: int = GA_GENERATIONS


class GAOptimizer:
    """
    遗传算法优化器：为给定档位进化出最优号码池。

    典型用法：
        ga = GAOptimizer(cfg)
        best, meta = ga.run()
        # best = Chromosome(red_genes=[...], blue_genes=[...], fitness=0.xxx)
        # meta = {"generations": 200, "pop_size": 100, ...}
    """

    def __init__(self, cfg: GAConfig, seed: Optional[int] = None):
        self.cfg = cfg
        if seed is not None:
            random.seed(seed)
        self._n_red = cfg.red_pool_size
        self._n_blue = cfg.blue_pool_size
        self._all_red = list(cfg.red_freq_scores.keys())
        self._all_blue = list(cfg.blue_freq_scores.keys())
        # 排个序方便按频率切热/冷
        self._red_sorted = sorted(cfg.red_freq_scores.keys(),
                                  key=lambda x: cfg.red_freq_scores[x], reverse=True)
        self._blue_sorted = sorted(cfg.blue_freq_scores.keys(),
                                   key=lambda x: cfg.blue_freq_scores[x], reverse=True)

    # ---------- 种群初始化 ----------

    def _init_individual(self) -> Chromosome:
        """
        生成一个初始个体：70% 来自热号池，30% 来自冷门池。
        """
        def _pick(pool_sorted, target_n, n_max, freq_scores):
            hot_count = max(1, int(target_n * GA_HOT_RATIO))
            cold_count = target_n - hot_count

            result = set()
            # 热号：从频率 Top 50% 里抽
            hot_pool = pool_sorted[:max(target_n * 2, len(pool_sorted) // 2)]
            while len(result) < hot_count and hot_pool:
                n = random.choice(hot_pool)
                result.add(n)
            # 冷门：从频率 Bottom 30% 里抽
            cold_pool = pool_sorted[-max(target_n, len(pool_sorted) // 3):]
            while len(result) < target_n:
                n = random.choice(cold_pool)
                result.add(n)
            return sorted(result)

        reds = _pick(self._red_sorted, self._n_red, self.cfg.red_max, self.cfg.red_freq_scores)
        blues = _pick(self._blue_sorted, self._n_blue, self.cfg.blue_max, self.cfg.blue_freq_scores)
        return Chromosome(red_genes=reds, blue_genes=blues)

    def _init_population(self) -> List[Chromosome]:
        seen = set()
        pop: List[Chromosome] = []
        for _ in range(self.cfg.pop_size * 3):   # 多生成一点去重
            ind = self._init_individual()
            k = ind.key()
            if k not in seen:
                seen.add(k)
                pop.append(ind)
            if len(pop) >= self.cfg.pop_size:
                break
        # 实在不够，补随机
        while len(pop) < self.cfg.pop_size:
            pop.append(self._init_individual())
        return pop

    # ---------- 适应度 ----------

    def _fitness(self, ind: Chromosome) -> float:
        """
        归一化 fitness ∈ [0, 1]。
        """
        # 1. 频率加权分（号码本身质量）
        red_freq_sum = sum(self.cfg.red_freq_scores.get(r, 0.0) for r in ind.red_genes)
        blue_freq_sum = sum(self.cfg.blue_freq_scores.get(b, 0.0) for b in ind.blue_genes)
        # 归一化：除以候选池 Top-N 理论最大值
        top_red = self._red_sorted[:self._n_red]
        top_blue = self._blue_sorted[:self._n_blue]
        top_red_sum = sum(self.cfg.red_freq_scores.get(r, 0.0) for r in top_red) or 1.0
        top_blue_sum = sum(self.cfg.blue_freq_scores.get(b, 0.0) for b in top_blue) or 1.0
        freq_score = (red_freq_sum / top_red_sum + blue_freq_sum / top_blue_sum) / 2.0
        freq_score = min(1.0, freq_score)

        # 2. 区间覆盖 + 奇偶均衡
        cov_score = self._coverage_score(ind)

        # 3. 近 N 期历史回测
        hist_score = self._history_score(ind)

        # 4. 与已优化档位的号码重合惩罚（档位间差异化）
        overlap_penalty = self._overlap_penalty(ind)

        # 5. 注数爆炸惩罚（软约束，金额超阈值扣分）
        cost_penalty = self._cost_penalty()

        fitness = (
            W_FREQ * freq_score +
            W_COVERAGE * cov_score +
            W_HIST * hist_score -
            W_OVERLAP * overlap_penalty -
            W_COST * cost_penalty
        )
        return max(0.0, min(1.0, fitness))

    def _coverage_score(self, ind: Chromosome) -> float:
        """
        红三区覆盖 + 奇偶比均衡 + 大小比均衡。
        ssq 红三区: 1-11, 12-22, 23-33  |  dlt 前区三区: 1-12, 13-24, 25-35
        蓝球: 奇偶 + 大小
        """
        if self.cfg.lottery_type == "ssq":
            z1, z2, z3 = (11, 22, 33)
            small_mid = 16    # 1-16 小 / 17-33 大
            blue_small = 8    # 蓝 1-8 小 / 9-16 大
        else:
            z1, z2, z3 = (12, 24, 35)
            small_mid = 17
            blue_small = 6    # 后区 1-6 小 / 7-12 大

        reds = ind.red_genes
        # 三区覆盖（0/1 每区是否至少有一个号）
        zone_hits = (
            sum(1 for r in reds if 1 <= r <= z1),
            sum(1 for r in reds if z1 + 1 <= r <= z2),
            sum(1 for r in reds if z2 + 1 <= r <= z3),
        )
        zone_score = sum(1 for z in zone_hits if z > 0) / 3.0

        # 奇偶均衡：最理想 = pool_size // 2 奇 + 其余偶
        odd_red = sum(1 for r in reds if r % 2 == 1)
        ideal_odd = len(reds) / 2.0
        odd_score = 1.0 - min(1.0, abs(odd_red - ideal_odd) / max(1, len(reds)))

        # 大小均衡
        small_red = sum(1 for r in reds if r <= small_mid)
        ideal_small = len(reds) / 2.0
        small_score = 1.0 - min(1.0, abs(small_red - ideal_small) / max(1, len(reds)))

        # 蓝球覆盖（若有多个蓝球）
        blue_score = 1.0
        if len(ind.blue_genes) >= 2:
            odd_blue = sum(1 for b in ind.blue_genes if b % 2 == 1)
            ideal_blue_odd = len(ind.blue_genes) / 2.0
            blue_score = 1.0 - min(1.0, abs(odd_blue - ideal_blue_odd) / len(ind.blue_genes))

        return (zone_score + odd_score + small_score + blue_score) / 4.0

    def _history_score(self, ind: Chromosome) -> float:
        """
        用近 N 期历史开奖号做回测：号码池里的红球有多少期至少中 1 个？
        归一化到 [0, 1]。
        """
        if not self.cfg.history_draws:
            return 0.5  # 没历史就给个中性分

        pool_red = set(ind.red_genes)
        pool_blue = set(ind.blue_genes)

        hit_periods = 0
        total_red_hit_counts = 0
        for draw in self.cfg.history_draws:
            # draw 格式统一：{"red": [...], "blue": [...]}
            draw_red = set(draw.get("red", []))
            draw_blue = set(draw.get("blue", []))
            red_hit = len(pool_red & draw_red)
            blue_hit = len(pool_blue & draw_blue)
            total_red_hit_counts += red_hit
            if red_hit >= 2 and blue_hit >= 1:
                hit_periods += 1
            elif red_hit >= 3:
                hit_periods += 1

        # 两种指标取平均：期命中比 + 平均命中数比
        period_hit_ratio = hit_periods / len(self.cfg.history_draws)
        # 理论最大值：每期最多命中 min(len(pool), 开奖pick_red) 个
        max_per_draw = min(len(pool_red), self.cfg.pick_red)
        avg_hit_ratio = (total_red_hit_counts / len(self.cfg.history_draws)) / max(1, max_per_draw)
        return min(1.0, (period_hit_ratio + avg_hit_ratio) / 2.0)

    def _overlap_penalty(self, ind: Chromosome) -> float:
        """
        与已优化档位的号码重合比例（越高越惩罚）。
        让不同档位有差异化，避免 8+2 和 9+2 几乎是同一个池。
        """
        if not self.cfg.optimized_pools:
            return 0.0
        pool_red = set(ind.red_genes)
        pool_blue = set(ind.blue_genes)
        max_overlap = 0.0
        for opt in self.cfg.optimized_pools:
            opt_red = set(opt.get("red_pool", []))
            opt_blue = set(opt.get("blue_pool", []))
            if not opt_red:
                continue
            ratio_r = len(pool_red & opt_red) / max(1, min(len(pool_red), len(opt_red)))
            ratio_b = len(pool_blue & opt_blue) / max(1, min(len(pool_blue), len(opt_blue))) if opt_blue else 0
            max_overlap = max(max_overlap, (ratio_r + ratio_b) / 2.0)
        return max_overlap

    def _cost_penalty(self) -> float:
        """
        注数爆炸软惩罚：金额 > ¥1000 开始扣分，> ¥5000 满扣分。
        """
        from math import comb
        bet_count = (comb(self._n_red, self.cfg.pick_red) *
                    comb(self._n_blue, self.cfg.pick_blue))
        amount = bet_count * self.cfg.ball_unit

        if amount <= 1000:
            return 0.0
        if amount >= 5000:
            return 1.0
        return (amount - 1000) / 4000.0

    # ---------- 遗传算子 ----------

    def _tournament_select(self, pop: List[Chromosome]) -> Chromosome:
        chosen = random.sample(pop, GA_TOURNAMENT_SIZE)
        return max(chosen, key=lambda x: x.fitness)

    def _crossover(self, p1: Chromosome, p2: Chromosome) -> Chromosome:
        """
        均匀交叉：红球和蓝球分别做 set 运算，保证不重复且满足大小。
        """
        def _cross_genes(a, b, target_n, freq_scores, pool_sorted, reverse_mutation=False):
            union = list(set(a) | set(b))
            if len(union) <= target_n:
                # 不够就从候选池补
                pool = list(pool_sorted)
                random.shuffle(pool)
                for n in pool:
                    if n not in union:
                        union.append(n)
                    if len(union) >= target_n:
                        break
                return sorted(union[:target_n])
            # 够多 → 按频率分从 union 里挑 Top-N（带一点随机）
            scored = [(n, freq_scores.get(n, 0)) for n in union]
            # 加随机扰动
            for i, (n, s) in enumerate(scored):
                scored[i] = (n, s + random.uniform(-0.05, 0.05))
            scored.sort(key=lambda x: x[1], reverse=True)
            return sorted([n for n, _ in scored[:target_n]])

        reds = _cross_genes(p1.red_genes, p2.red_genes, self._n_red,
                            self.cfg.red_freq_scores, self._red_sorted)
        blues = _cross_genes(p1.blue_genes, p2.blue_genes, self._n_blue,
                             self.cfg.blue_freq_scores, self._blue_sorted)
        return Chromosome(red_genes=reds, blue_genes=blues)

    def _mutate(self, ind: Chromosome) -> Chromosome:
        """
        普通变异：随机换一个基因 → 换成候选池里另一个号码。
        反向变异（20%）：换成最冷门的号码。
        """
        def _mutate_genes(genes, target_n, all_pool, freq_scores, pool_sorted):
            genes = list(genes)
            idx = random.randint(0, len(genes) - 1)
            current = genes[idx]
            # 选候选替换
            if random.random() < GA_REVERSE_MUTATION_RATE:
                # 反向：从最冷门的 30% 里抽
                cold_pool = pool_sorted[-max(target_n, len(pool_sorted) // 3):]
                candidates = [n for n in cold_pool if n != current]
            else:
                # 常规：从全部候选里抽一个不同的
                candidates = [n for n in all_pool if n != current and n not in genes]
            if candidates:
                genes[idx] = random.choice(candidates)
            return sorted(genes)

        new_reds = _mutate_genes(ind.red_genes, self._n_red,
                                 self._all_red, self.cfg.red_freq_scores, self._red_sorted)
        new_blues = _mutate_genes(ind.blue_genes, self._n_blue,
                                  self._all_blue, self.cfg.blue_freq_scores, self._blue_sorted)
        return Chromosome(red_genes=new_reds, blue_genes=new_blues)

    # ---------- 主循环 ----------

    def run(self) -> Tuple[Chromosome, Dict]:
        pop = self._init_population()
        for ind in pop:
            ind.fitness = self._fitness(ind)

        best_ever = max(pop, key=lambda x: x.fitness)
        history_best = []
        history_avg = []

        for gen in range(self.cfg.generations):
            # 精英保留
            pop_sorted = sorted(pop, key=lambda x: x.fitness, reverse=True)
            elites = pop_sorted[:GA_ELITE_COUNT]

            # 生成新一代
            new_pop = [Chromosome(r.red_genes[:], b.blue_genes[:])
                       for r, b in zip(elites,
                                       [Chromosome(red_genes=e.red_genes, blue_genes=e.blue_genes)
                                        for e in elites])]
            # 上一行写法啰嗦，简化：
            new_pop = [Chromosome(red_genes=e.red_genes[:],
                                  blue_genes=e.blue_genes[:],
                                  fitness=e.fitness) for e in elites]

            while len(new_pop) < self.cfg.pop_size:
                p1 = self._tournament_select(pop)
                p2 = self._tournament_select(pop)

                if random.random() < GA_CROSSOVER_RATE:
                    child = self._crossover(p1, p2)
                else:
                    child = Chromosome(red_genes=p1.red_genes[:],
                                       blue_genes=p1.blue_genes[:])

                if random.random() < GA_MUTATION_RATE:
                    child = self._mutate(child)

                child.fitness = self._fitness(child)
                new_pop.append(child)

            pop = new_pop

            gen_best = max(pop, key=lambda x: x.fitness)
            gen_avg = sum(x.fitness for x in pop) / len(pop)
            history_best.append(gen_best.fitness)
            history_avg.append(gen_avg)

            if gen_best.fitness > best_ever.fitness:
                best_ever = Chromosome(red_genes=gen_best.red_genes[:],
                                       blue_genes=gen_best.blue_genes[:],
                                       fitness=gen_best.fitness)

        meta = {
            "generations": self.cfg.generations,
            "pop_size": self.cfg.pop_size,
            "final_fitness": round(best_ever.fitness, 4),
            "final_red_pool_size": len(best_ever.red_genes),
            "final_blue_pool_size": len(best_ever.blue_genes),
            "history_best_last5": [round(x, 4) for x in history_best[-5:]],
            "history_avg_last5": [round(x, 4) for x in history_avg[-5:]],
            "optimized_pools_considered": len(self.cfg.optimized_pools or []),
        }
        return best_ever, meta
