<template>
  <div class="hit-page">
    <!-- ===== 工具栏 ===== -->
    <el-card class="toolbar-card" shadow="hover">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-radio-group v-model="lotteryType" @change="onTypeChange" size="default">
            <el-radio-button value="ssq">🟥 双色球</el-radio-button>
            <el-radio-button value="dlt">🟧 大乐透</el-radio-button>
          </el-radio-group>
          <el-select
            v-model="selectedIssue"
            placeholder="选择历史开奖期"
            filterable
            class="issue-select"
            @change="fetchDetail"
          >
            <el-option
              v-for="d in draws"
              :key="d.issue_num"
              :value="d.issue_num"
              :label="`${d.issue_num} 期（${d.draw_date}）· ${d.forecast_count} 条预测`"
            />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button size="default" @click="fetchDraws" :loading="loading" type="primary" plain>
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- ===== 加载状态 ===== -->
    <div v-if="loading" class="loading-container">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>加载中...</span>
    </div>

    <!-- ===== 空状态 ===== -->
    <el-empty v-else-if="!detail" description="请选择历史开奖期进行命中分析" />

    <!-- ===== 分析结果 ===== -->
    <div v-else>
      <!-- ---- 开奖号码 + 概览 ---- -->
      <el-card class="draw-card" shadow="hover">
        <div class="draw-header">
          <span class="draw-icon">🎯</span>
          <span class="draw-title">{{ lotteryName }}第 {{ detail.draw.issue_num }} 期开奖结果</span>
          <el-tag type="warning" size="small" round>{{ detail.draw.draw_date }}</el-tag>
        </div>
        <div class="draw-numbers">
          <div class="number-row">
            <span class="label">🔴 {{ lotteryType === 'ssq' ? '红球' : '前区' }}</span>
            <div class="number-group">
              <span v-for="r in detail.draw.red" :key="r" class="ball ball-red">
                {{ String(r).padStart(2, '0') }}
              </span>
            </div>
          </div>
          <div class="number-row">
            <span class="label">🔵 {{ lotteryType === 'ssq' ? '蓝球' : '后区' }}</span>
            <div class="number-group">
              <span v-for="b in detail.draw.blue" :key="b" class="ball ball-blue">
                {{ String(b).padStart(2, '0') }}
              </span>
            </div>
          </div>
        </div>

        <el-row :gutter="12" class="overview-row">
          <el-col :xs="12" :sm="8">
            <div class="overview-item">
              <div class="overview-value">{{ detail.total_forecasts }}</div>
              <div class="overview-label">对标预测总数</div>
            </div>
          </el-col>
          <el-col :xs="12" :sm="8">
            <div class="overview-item overview-win">
              <div class="overview-value" style="color:#e6a23c;">{{ detail.win_count }}</div>
              <div class="overview-label">中奖预测数</div>
            </div>
          </el-col>
          <el-col :xs="24" :sm="8">
            <div class="overview-item overview-best">
              <div class="overview-value">{{ bestHit.total_hits }} 中</div>
              <div class="overview-label">
                最佳战绩<span v-if="bestHit.prize && bestHit.prize !== '未中奖'"> · {{ bestHit.prize }}</span>
              </div>
            </div>
          </el-col>
        </el-row>
      </el-card>

      <!-- ---- 命中数分布 ---- -->
      <el-card class="dist-card" shadow="hover">
        <template #header>
          <span class="card-title">📊 命中数分布</span>
        </template>
        <div class="dist-bars">
          <div v-for="d in detail.hit_distribution" :key="d.total_hits" class="dist-row">
            <span class="dist-label">{{ d.total_hits }} 中</span>
            <div class="dist-track">
              <div
                class="dist-seg dist-count-bar"
                :style="{ width: distPct(d.count) + '%' }"
                :title="`${d.count} 条`"
              ></div>
            </div>
            <span class="dist-count">{{ d.count }}</span>
          </div>
        </div>
      </el-card>

      <!-- ---- 奖级汇总 ---- -->
      <el-card v-if="detail.prize_summary.length" class="prize-card" shadow="hover">
        <template #header>
          <span class="card-title">🏆 中奖奖级汇总（按官方规则判定）</span>
        </template>
        <div class="prize-tags">
          <div v-for="p in detail.prize_summary" :key="p.prize" class="prize-tag-item">
            <el-tag :type="prizeTagType(p.prize)" size="large" effect="dark" round>
              {{ p.prize }}
            </el-tag>
            <span class="prize-count">
              <strong style="color:#f56c6c;">{{ p.count }}</strong> 注
            </span>
          </div>
        </div>
      </el-card>

      <!-- ---- 本期复试方案命中（与本期结果预测同源） ---- -->
      <el-card v-if="detail.fushi_present" class="fushi-hit-card" shadow="hover">
        <template #header>
          <div class="list-header">
            <span class="card-title">🎲 本期复试方案命中（基于本期预测号码池）</span>
            <el-tag type="primary" size="small" round>{{ detail.fushi_plans.length }} 档</el-tag>
          </div>
        </template>

        <el-row :gutter="12">
          <el-col
            v-for="p in detail.fushi_plans"
            :key="p.pattern"
            :xs="24" :sm="12" :md="8" :lg="6"
          >
            <div class="fushi-hit-plan" :class="{ 'plan-win': p.is_history_hit }">
              <div class="plan-head">
                <span class="plan-pattern">{{ p.pattern }}</span>
                <el-tag
                  :type="p.is_history_hit ? 'success' : 'info'"
                  size="small" round
                  effect="dark"
                >
                  {{ p.prize_level }}
                </el-tag>
              </div>
              <div class="plan-stats-mini">
                <span>注数 <b>{{ p.bet_count }}</b></span>
                <span>投入 <b>¥{{ p.bet_amount }}</b></span>
              </div>
              <div class="plan-prize-row">
                <span class="prize-money" :class="{ 'prize-win': p.prize_amount > 0 }">
                  中奖 ¥{{ p.prize_amount || 0 }}
                </span>
                <span
                  class="prize-profit"
                  :class="p.profit >= 0 ? 'profit-up' : 'profit-down'"
                >
                  {{ p.profit >= 0 ? '盈' : '亏' }} ¥{{ Math.abs(p.profit || 0) }}
                </span>
              </div>
              <div class="plan-prize-detail" v-if="p.prize_detail && Object.keys(p.prize_detail).length">
                <el-tag
                  v-for="(cnt, lvl) in p.prize_detail"
                  :key="lvl"
                  size="small"
                  :type="lvl === '一等奖' || lvl === '二等奖' ? 'danger' : 'success'"
                  effect="plain"
                >{{ lvl }} × {{ cnt }}</el-tag>
                <el-tag
                  v-if="p.float_prize_count > 0"
                  size="small"
                  type="warning"
                  effect="plain"
                >浮动奖 {{ p.float_prize_count }} 注待官方核算</el-tag>
              </div>
              <div class="plan-red-pool">
                <span class="pool-label">🔴</span>
                <span
                  v-for="r in p.red_pool"
                  :key="r"
                  class="ball ball-red ball-tiny"
                  :class="{ 'ball-wasm': isInDraw(r, detail.draw.red) }"
                >{{ String(r).padStart(2, '0') }}</span>
              </div>
              <div class="plan-blue-pool">
                <span class="pool-label">🔵</span>
                <span
                  v-for="b in p.blue_pool"
                  :key="b"
                  class="ball ball-blue ball-tiny"
                  :class="{ 'ball-wasm': isInDraw(b, detail.draw.blue) }"
                >{{ String(b).padStart(2, '0') }}</span>
              </div>
              <div class="plan-hit-dist" v-if="p.is_history_hit">
                <span class="dist-tag">红命中 {{ formatDist(p.hit_reds) }}</span>
                <span class="dist-tag">蓝命中 {{ formatDist(p.hit_blues) }}</span>
              </div>
            </div>
          </el-col>
        </el-row>
      </el-card>

      <!-- ---- 命中明细 ---- -->
      <el-card class="list-card" shadow="hover">
        <template #header>
          <div class="list-header">
            <span class="card-title">📋 预测命中明细（按命中数降序）</span>
            <el-tag type="info" size="small" round>共 {{ detail.total_forecasts }} 条</el-tag>
          </div>
        </template>

        <el-table
          :data="pagedItems"
          border
          stripe
          style="width:100%;"
          size="default"
          max-height="560"
        >
          <el-table-column label="排名" width="70" align="center">
            <template #default="{ $index }">
              <span class="rank-badge" :class="rankClass($index + (currentPage - 1) * pageSize)">{{ $index + 1 + (currentPage - 1) * pageSize }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="lotteryType === 'ssq' ? '红球' : '前区'" min-width="260">
            <template #default="{ row }">
              <span
                v-for="r in row.red"
                :key="r"
                class="ball ball-red ball-small"
                :class="{ 'ball-hit': row.hit_red_numbers.includes(r) }"
              >
                {{ String(r).padStart(2, '0') }}
              </span>
            </template>
          </el-table-column>
          <el-table-column :label="lotteryType === 'ssq' ? '蓝球' : '后区'" width="120">
            <template #default="{ row }">
              <span
                v-for="b in row.blue"
                :key="b"
                class="ball ball-blue ball-small"
                :class="{ 'ball-hit': row.hit_blue_numbers.includes(b) }"
              >
                {{ String(b).padStart(2, '0') }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="红命中" width="90" align="center">
            <template #default="{ row }">
              <span class="hit-num hit-red">{{ row.red_hits }}</span>
              <span class="hit-total">/ {{ lotteryType === 'ssq' ? 6 : 5 }}</span>
            </template>
          </el-table-column>
          <el-table-column label="蓝命中" width="90" align="center">
            <template #default="{ row }">
              <span class="hit-num hit-blue">{{ row.blue_hits }}</span>
              <span class="hit-total">/ {{ lotteryType === 'ssq' ? 1 : 2 }}</span>
            </template>
          </el-table-column>
          <el-table-column label="总命中" width="90" align="center">
            <template #default="{ row }">
              <span class="hit-total-num" :class="'hit-total-' + row.total_hits">{{ row.total_hits }}</span>
              <span class="hit-total">/ 7</span>
            </template>
          </el-table-column>
          <el-table-column label="奖级" width="100" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.prize !== '未中奖'" :type="prizeTagType(row.prize)" size="small" effect="dark">
                {{ row.prize }}
              </el-tag>
              <span v-else style="color:#c0c4cc;">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="quality_score" label="质量评分" width="150">
            <template #default="{ row }">
              <el-progress
                :percentage="Math.round((row.quality_score || 0) * 100)"
                :color="getScoreColor(row.quality_score || 0)"
                :stroke-width="6"
                style="width:110px;display:inline-block;"
              />
            </template>
          </el-table-column>
          <el-table-column prop="model_version" label="模型版本" min-width="160" show-overflow-tooltip />
        </el-table>

        <div class="pagination-wrapper">
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[20, 50, 100, 200]"
            :total="detail.total_forecasts"
            layout="total, sizes, prev, pager, next"
            small
            @size-change="onPageSizeChange"
            @current-change="onPageChange"
          />
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Loading, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getAnalyzableDraws, getDrawHitAnalysis } from '@/api/hitAnalysis'

const lotteryType = ref('ssq')
const draws = ref([])
const selectedIssue = ref('')
const detail = ref(null)
const loading = ref(false)

// 分页
const currentPage = ref(1)
const pageSize = ref(20)

// 彩种中文名
const lotteryName = computed(() => lotteryType.value === 'ssq' ? '双色球' : '大乐透')

// 最佳命中（明细已按命中降序，取第一条）
const bestHit = computed(() => {
  const first = detail.value?.items?.[0]
  if (!first) return { total_hits: 0, prize: '未中奖' }
  return { total_hits: first.total_hits, prize: first.prize }
})

// 明细分页（全部预测，不再区分保留/剔除）
const pagedItems = computed(() => {
  const items = detail.value?.items || []
  const start = (currentPage.value - 1) * pageSize.value
  return items.slice(start, start + pageSize.value)
})

// 命中分布条宽度百分比（按总数归一化）
const distPct = (count) => {
  const total = detail.value?.total_forecasts || 0
  if (total === 0) return 0
  return count / total * 100
}

// 奖级标签颜色
const prizeTagType = (prize) => {
  if (['一等奖', '二等奖', '三等奖'].includes(prize)) return 'danger'
  if (['四等奖', '五等奖', '六等奖'].includes(prize)) return 'warning'
  return 'primary'
}

const getScoreColor = (score) => {
  const pct = score * 100
  if (pct >= 70) return '#67C23A'
  if (pct >= 50) return '#E6A23C'
  return '#909399'
}

// 复试池球是否中了（开奖 vs 池）
const isInDraw = (num, drawNums) => Array.isArray(drawNums) && drawNums.includes(num)

// hit_reds/hit_blues dict 格式化
const formatDist = (dist) => {
  if (!dist) return '-'
  // dist 形如 {"0":5,"1":12,"2":18}
  const pairs = Object.entries(dist).sort((a, b) => Number(a[0]) - Number(b[0]))
  return pairs.map(([k, v]) => `${k}中×${v}`).join('  ')
}

// 前三名排名样式
const rankClass = (rank) => {
  if (rank === 1) return 'rank-gold'
  if (rank === 2) return 'rank-silver'
  if (rank === 3) return 'rank-bronze'
  return ''
}

// ---- 加载可分析期数列表 ----
const fetchDraws = async () => {
  loading.value = true
  try {
    const res = await getAnalyzableDraws(lotteryType.value, 200)
    draws.value = res.items || []
    if (draws.value.length === 0) {
      selectedIssue.value = ''
      detail.value = null
      ElMessage.info('近期暂无对标预测记录的开奖期')
      return
    }
    // 当前选择仍存在则保留，否则默认选最新一期
    if (!draws.value.find(d => d.issue_num === selectedIssue.value)) {
      selectedIssue.value = draws.value[0].issue_num
    }
    await fetchDetail()
  } catch (e) {
    console.error('加载可分析期数失败:', e)
    ElMessage.error('加载期数列表失败：' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

// ---- 加载命中分析明细 ----
const fetchDetail = async () => {
  if (!selectedIssue.value) return
  loading.value = true
  try {
    detail.value = await getDrawHitAnalysis(lotteryType.value, selectedIssue.value)
    currentPage.value = 1
  } catch (e) {
    console.error('加载命中分析失败:', e)
    detail.value = null
  } finally {
    loading.value = false
  }
}

// 切换彩种：重置选择并重新加载
const onTypeChange = () => {
  selectedIssue.value = ''
  detail.value = null
  fetchDraws()
}

const onPageChange = (page) => { currentPage.value = page }
const onPageSizeChange = (size) => {
  pageSize.value = size
  currentPage.value = 1
}

onMounted(fetchDraws)
</script>

<style scoped>
.hit-page {
  padding: 16px;
  max-width: 1400px;
  margin: 0 auto;
}

/* 工具栏 */
.toolbar-card { margin-bottom: 16px; border-radius: 12px; }
.toolbar-card :deep(.el-card__body) { padding: 10px 16px; }
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.toolbar-left { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.toolbar-right { display: flex; align-items: center; gap: 12px; }
.issue-select { width: 340px; }

/* 加载状态 */
.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 60px 0;
  font-size: 16px;
  color: #409EFF;
  gap: 10px;
}

/* 开奖卡片 */
.draw-card { margin-bottom: 16px; border-radius: 12px; }
.draw-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.draw-icon { font-size: 18px; }
.draw-title { font-size: 17px; font-weight: 600; color: #303133; }
.draw-numbers {
  background: linear-gradient(135deg, #fdf6ec 0%, #faefe2 100%);
  border-radius: 10px;
  padding: 14px 16px;
  border-left: 4px solid #e6a23c;
}
.number-row {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.number-row:last-child { margin-bottom: 0; }
.label { font-weight: 600; color: #606266; width: 64px; flex-shrink: 0; font-size: 14px; }
.number-group { display: flex; flex-wrap: wrap; gap: 4px; }

/* 号码球 */
.ball {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  margin: 0 3px;
  transition: all 0.2s;
}
.ball-red { background: linear-gradient(145deg, #f56c6c, #d94a4a); box-shadow: 0 2px 6px rgba(245, 108, 108, 0.35); }
.ball-blue { background: linear-gradient(145deg, #409EFF, #2b7fd4); box-shadow: 0 2px 6px rgba(64, 158, 255, 0.35); }
.ball-small { width: 28px; height: 28px; font-size: 12px; margin: 0 2px; }
.ball-hit {
  box-shadow: 0 0 0 3px #67C23A, 0 2px 10px rgba(103, 194, 58, 0.5);
  transform: scale(1.08);
}

/* 概览 */
.overview-row { margin-top: 14px; }
.overview-item {
  text-align: center;
  padding: 10px 0;
  background: #f5f7fa;
  border-radius: 8px;
}
.overview-win { background: #fdf6ec; }
.overview-best { background: linear-gradient(135deg, #f0f9ff, #e3f0fa); }
.overview-value { font-size: 22px; font-weight: 700; color: #409EFF; }
.overview-label { font-size: 13px; color: #909399; margin-top: 2px; }

/* 卡片通用 */
.dist-card, .prize-card, .list-card { margin-bottom: 16px; border-radius: 12px; }
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.card-title { font-size: 15px; font-weight: 600; color: #303133; }

/* 命中分布 */
.dist-bars {
  background: #f9fafc;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px 14px;
}
.dist-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.dist-row:last-child { margin-bottom: 0; }
.dist-label { width: 48px; font-size: 13px; color: #606266; font-weight: 600; flex-shrink: 0; }
.dist-track {
  flex: 1;
  height: 20px;
  background: #f0f2f5;
  border-radius: 10px;
  overflow: hidden;
  display: flex;
}
.dist-seg { height: 100%; transition: width 0.4s ease; }
.dist-count-bar { background: linear-gradient(90deg, #79bbff, #409EFF); }
.dist-count { width: 50px; text-align: right; font-size: 13px; font-weight: 600; color: #409EFF; flex-shrink: 0; }

/* 奖级汇总 */
.prize-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 14px 24px;
}
.prize-tag-item { display: flex; align-items: center; gap: 8px; }
.prize-count { font-size: 13px; color: #606266; }

/* 明细表 */
.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.list-card :deep(.el-table) { border-radius: 8px; overflow: hidden; }
.list-card :deep(.el-table th) { background: #f5f7fa; }

.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #f0f2f5;
  color: #606266;
  font-weight: 700;
  font-size: 13px;
}
.rank-gold { background: linear-gradient(145deg, #ffd666, #f7a823); color: #fff; }
.rank-silver { background: linear-gradient(145deg, #dcdfe6, #b1b3b8); color: #fff; }
.rank-bronze { background: linear-gradient(145deg, #f5c19b, #d4925a); color: #fff; }

.hit-num { font-size: 18px; font-weight: 700; }
.hit-red { color: #f56c6c; }
.hit-blue { color: #409EFF; }
.hit-total { font-size: 12px; color: #909399; }
.hit-total-num {
  display: inline-block;
  min-width: 26px;
  height: 26px;
  line-height: 26px;
  border-radius: 13px;
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  background: #c0c4cc;
}
.hit-total-7 { background: linear-gradient(145deg, #ff6b6b, #e63946); box-shadow: 0 2px 8px rgba(230, 57, 70, 0.4); }
.hit-total-6 { background: linear-gradient(145deg, #f7a823, #e68a00); }
.hit-total-5 { background: linear-gradient(145deg, #e6a23c, #cf8a1f); }
.hit-total-4 { background: linear-gradient(145deg, #85ce61, #67C23A); }
.hit-total-3 { background: linear-gradient(145deg, #79bbff, #409EFF); }

/* 分页 */
.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  padding-top: 14px;
  margin-top: 6px;
  border-top: 1px solid #ebeef5;
}

/* ===== 复试方案历史命中卡片 ===== */
.fushi-hit-card { margin-bottom: 16px; }

.fushi-hit-plan {
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
  transition: all 0.2s;
}
.fushi-hit-plan:hover {
  border-color: #1890ff;
  box-shadow: 0 2px 8px rgba(24, 144, 255, 0.12);
}
.fushi-hit-plan.plan-win {
  background: linear-gradient(135deg, #f0f9eb 0%, #e1f3d8 100%);
  border-color: #67c23a;
}

.plan-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.plan-pattern {
  font-size: 17px;
  font-weight: 700;
  color: #1890ff;
}

.plan-stats-mini {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #606266;
  margin-bottom: 8px;
  padding: 4px 6px;
  background: rgba(255,255,255,0.6);
  border-radius: 4px;
}
.plan-stats-mini b { color: #f56c6c; font-size: 14px; }

/* 中奖金额 / 盈亏 */
.plan-prize-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.prize-money {
  font-size: 13px;
  font-weight: 600;
  color: #909399;
}
.prize-money.prize-win {
  color: #f56c6c;
  font-size: 15px;
}
.prize-profit {
  font-size: 12px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 10px;
}
.prize-profit.profit-up {
  color: #67c23a;
  background: #f0f9eb;
}
.prize-profit.profit-down {
  color: #909399;
  background: #f4f4f5;
}
.plan-prize-detail {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}

.plan-red-pool, .plan-blue-pool {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}
.pool-label {
  font-size: 11px;
  margin-right: 4px;
}

.ball-tiny {
  width: 20px !important;
  height: 20px !important;
  font-size: 10px !important;
  line-height: 20px !important;
  padding: 0 !important;
  margin: 0 !important;
}
.ball-wasm {
  outline: 2px solid #f56c6c;
  outline-offset: -2px;
  position: relative;
}
.ball-wasm::after {
  content: '✓';
  position: absolute;
  top: -6px;
  right: -6px;
  font-size: 10px;
  color: #f56c6c;
  background: #fff;
  border-radius: 50%;
  width: 14px;
  height: 14px;
  line-height: 14px;
  text-align: center;
  font-weight: 700;
}

.plan-hit-dist {
  margin-top: 6px;
  padding: 6px 8px;
  background: #fff;
  border-radius: 4px;
  border: 1px dashed #67c23a;
  font-size: 11px;
  color: #606266;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.dist-tag {
  color: #67c23a;
  font-weight: 600;
}

/* 响应式 */
@media (max-width: 768px) {
  .hit-page { padding: 8px; }
  .toolbar { flex-direction: column; align-items: stretch; }
  .toolbar-left { justify-content: center; }
  .issue-select { width: 100%; }
  .ball { width: 30px; height: 30px; font-size: 13px; }
  .ball-small { width: 24px; height: 24px; font-size: 11px; }
  .number-row { flex-direction: column; align-items: flex-start; gap: 4px; }
  .label { width: auto; }
  .pagination-wrapper { justify-content: center; }
}
</style>
