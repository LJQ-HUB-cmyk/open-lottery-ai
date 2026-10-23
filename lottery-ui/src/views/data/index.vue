<template>
  <div class="data-container">
    <el-tabs v-model="activeTab">
      <!-- 双色球 Tab -->
      <el-tab-pane label="双色球" name="ssq">
        <el-table :data="ssqData" border stripe style="width: 100%; overflow-x: auto">
          <el-table-column prop="issue_num" label="期号" width="120" />
          <el-table-column prop="draw_date" label="日期" width="120" />
          <el-table-column label="红球" min-width="200">
            <template #default="{ row }">
              <el-tag
                v-for="i in 6"
                :key="i"
                size="small"
                style="margin:2px"
              >
                {{ row[`red_${['one','two','three','four','five','six'][i-1]}`] }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="蓝球" width="100">
            <template #default="{ row }">
              <el-tag type="danger" size="small">{{ row.blue_one }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="red_summation" label="和值" width="80" />
          <el-table-column prop="red_span" label="跨度" width="80" />
        </el-table>

        <!-- 分页组件 -->
        <div class="pagination-wrapper">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            @current-change="loadSSQ"
            :layout="isMobile ? 'prev, pager, next' : 'prev, pager, next, total'"
            size="small"
            class="mobile-pagination"
          />
        </div>
      </el-tab-pane>

      <!-- 大乐透 Tab -->
      <el-tab-pane label="大乐透" name="dlt">
        <el-table :data="dltData" border stripe style="width: 100%; overflow-x: auto">
          <el-table-column prop="issue_num" label="期号" width="120" />
          <el-table-column prop="draw_date" label="日期" width="120" />
          <el-table-column label="前区" min-width="180">
            <template #default="{ row }">
              <el-tag
                v-for="i in 5"
                :key="i"
                size="small"
                style="margin:2px"
              >
                {{ row[`front_${['one','two','three','four','five'][i-1]}`] }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="后区" width="120">
            <template #default="{ row }">
              <el-tag
                v-for="i in 2"
                :key="i"
                size="small"
                type="warning"
                style="margin:2px"
              >
                {{ row[`back_${['one','two'][i-1]}`] }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="front_summation" label="和值" width="80" />
          <el-table-column prop="front_span" label="跨度" width="80" />
        </el-table>

        <!-- 分页组件 -->
        <div class="pagination-wrapper">
          <el-pagination
            v-model:current-page="dltPage"
            v-model:page-size="dltPageSize"
            :total="dltTotal"
            @current-change="loadDLT"
            :layout="isMobile ? 'prev, pager, next' : 'prev, pager, next, total'"
            size="small"
            class="mobile-pagination"
          />
        </div>
      </el-tab-pane>

      <!-- 相似度分析 Tab -->
      <el-tab-pane label="🔬 相似度分析" name="similarity">
        <div class="sim-toolbar">
          <el-radio-group v-model="simLottery" size="default" @change="onSimLotteryChange">
            <el-radio-button value="ssq">🟥 双色球</el-radio-button>
            <el-radio-button value="dlt">🟧 大乐透</el-radio-button>
          </el-radio-group>
          <el-select v-model="simLimit" size="default" style="width:200px;">
            <el-option :value="0" :label="`全部（${simTotalMap[simLottery] || '...'} 期）`" />
            <el-option :value="100" label="最近 100 期" />
            <el-option :value="300" label="最近 300 期" />
            <el-option :value="500" label="最近 500 期" />
            <el-option :value="1000" label="最近 1000 期" />
            <el-option :value="1500" label="最近 1500 期" />
            <el-option :value="2000" label="最近 2000 期" />
          </el-select>
          <el-button type="primary" :loading="simLoading" @click="loadSimilarity">
            <el-icon><Refresh /></el-icon> 开始分析
          </el-button>
        </div>

        <div v-if="simLoading" class="sim-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>分析中（{{ simLottery }} × {{ simLimitLabel }}，O(n²) 约 {{ simLimitLabel === '全部' ? '全部数据' : (simLimit * simLimit / 2).toLocaleString() + ' 次对比' }}）...</span>
        </div>

        <template v-else-if="simData">
          <!-- 汇总卡片 -->
          <div class="sim-summary">
            <div class="summary-card">
              <div class="summary-value">{{ simData.analyzed }}</div>
              <div class="summary-label">分析期数</div>
            </div>
            <div class="summary-card">
              <div class="summary-value">{{ (simData.summary?.avg_similarity * 100).toFixed(1) }}%</div>
              <div class="summary-label">平均相似度</div>
            </div>
            <div class="summary-card">
              <div class="summary-value">{{ (simData.summary?.max_similarity * 100).toFixed(1) }}%</div>
              <div class="summary-label">最高相似度</div>
            </div>
            <div class="summary-card">
              <div class="summary-value">{{ (simData.summary?.median_similarity * 100).toFixed(1) }}%</div>
              <div class="summary-label">中位数相似度</div>
            </div>
            <div class="summary-card highlight">
              <div class="summary-value">{{ simData.summary?.high_similarity_count }}</div>
              <div class="summary-label">相似度 ≥40% 的期数（占 {{ simData.summary?.high_similarity_rate }}%）</div>
            </div>
          </div>

          <!-- 分布条形图 -->
          <div class="sim-section">
            <div class="sim-section-title">📊 相似度分布</div>
            <div class="dist-bars">
              <div v-for="(count, range) in simData.summary?.distribution" :key="range" class="dist-row">
                <span class="dist-label">{{ range }}</span>
                <div class="dist-bar-track">
                  <div class="dist-bar" :style="{ width: distPct(range, count) + '%', background: distColor(range) }"></div>
                </div>
                <span class="dist-count">{{ count }} 期</span>
                <span class="dist-pct">({{ distPct(range, count) }}%)</span>
              </div>
            </div>
          </div>

          <!-- TOP 10 最高相似度 -->
          <div class="sim-section">
            <div class="sim-section-title">🏆 最高相似度 TOP 10</div>
            <el-table :data="simData.summary?.top10_similar" border stripe size="small" style="width:100%;">
              <el-table-column type="index" label="#" width="50" />
              <el-table-column prop="issue_num" label="期号" width="110" />
              <el-table-column prop="draw_date" label="日期" width="110" />
              <el-table-column label="红球" min-width="220">
                <template #default="{ row }">
                  <span v-for="r in row.red" :key="r" class="sim-ball ball-red">{{ String(r).padStart(2,'0') }}</span>
                </template>
              </el-table-column>
              <el-table-column label="蓝球" width="120">
                <template #default="{ row }">
                  <template v-if="Array.isArray(row.blue)">
                    <span v-for="b in row.blue" :key="b" class="sim-ball ball-blue">{{ String(b).padStart(2,'0') }}</span>
                  </template>
                  <span v-else class="sim-ball ball-blue">{{ String(row.blue).padStart(2,'0') }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="max_similarity" label="最大相似度" width="140">
                <template #default="{ row }">
                  <el-tag :type="row.max_similarity >= 0.6 ? 'danger' : row.max_similarity >= 0.4 ? 'warning' : 'info'" size="small">
                    {{ (row.max_similarity * 100).toFixed(1) }}%
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="matched_history_issue" label="匹配历史期号" width="140" />
            </el-table>
          </div>

          <!-- 完整列表 -->
          <div class="sim-section">
            <div class="sim-section-title">📋 全部分析结果（最新在前）</div>
            <el-table
              :data="paginatedSimItems"
              border
              stripe
              size="small"
              max-height="500"
              style="width:100%;"
            >
              <el-table-column prop="issue_num" label="期号" width="110" />
              <el-table-column prop="draw_date" label="日期" width="110" />
              <el-table-column label="红球" min-width="220">
                <template #default="{ row }">
                  <span v-for="r in row.red" :key="r" class="sim-ball ball-red">{{ String(r).padStart(2,'0') }}</span>
                </template>
              </el-table-column>
              <el-table-column label="蓝球" width="120">
                <template #default="{ row }">
                  <template v-if="Array.isArray(row.blue)">
                    <span v-for="b in row.blue" :key="b" class="sim-ball ball-blue">{{ String(b).padStart(2,'0') }}</span>
                  </template>
                  <span v-else class="sim-ball ball-blue">{{ String(row.blue).padStart(2,'0') }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="max_similarity" label="最大相似度" width="140">
                <template #default="{ row }">
                  <el-progress
                    :percentage="Math.round(row.max_similarity * 100)"
                    :color="simProgressColor(row.max_similarity)"
                    :stroke-width="6"
                    style="width:120px;display:inline-block;"
                    :format="() => (row.max_similarity * 100).toFixed(1) + '%'"
                  />
                </template>
              </el-table-column>
              <el-table-column prop="matched_history_issue" label="匹配历史期号" width="140" />
            </el-table>

            <div class="pagination-wrapper">
              <el-pagination
                v-model:current-page="simPage"
                v-model:page-size="simPageSize"
                :page-sizes="[20, 50, 100]"
                :total="simData.items?.length || 0"
                layout="total, sizes, prev, pager, next"
                small
              />
            </div>
          </div>
        </template>

        <el-empty v-else description="点击「开始分析」按钮生成相似度分析结果" />
      </el-tab-pane>

      <!-- 走势图 Tab（懒加载：首次切换才挂载组件并请求数据） -->
      <el-tab-pane label="📈 走势图" name="trend" lazy>
        <TrendAnalysis />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useWindowSize } from '@vueuse/core'
import { Loading, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { listDLTData, listSSQData, getHistorySimilarity } from '@/api/data'
import TrendAnalysis from './TrendAnalysis.vue'

// ---------- 响应式窗口判断 ----------
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

// ---------- 双色球状态 ----------
const activeTab = ref('ssq')
const ssqData = ref([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

// ---------- 大乐透状态 ----------
const dltData = ref([])
const dltPage = ref(1)
const dltPageSize = ref(20)
const dltTotal = ref(0)

// ---------- 相似度分析状态 ----------
const simLottery = ref('ssq')
const simLimit = ref(0)           // 0 = 全部
const simTotalMap = ref({ ssq: null, dlt: null })  // 各彩种总期数
const simLoading = ref(false)
const simData = ref(null)
const simPage = ref(1)
const simPageSize = ref(20)

const simLimitLabel = computed(() => {
  if (simLimit.value === 0) return '全部'
  return `${simLimit.value} 期`
})

// ---------- 加载函数 ----------
const loadSSQ = async () => {
  try {
    const res = await listSSQData({
      limit: pageSize.value,
      offset: (page.value - 1) * pageSize.value
    })
    ssqData.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    console.error('加载双色球失败:', e)
  }
}

const loadDLT = async () => {
  try {
    const res = await listDLTData({
      limit: dltPageSize.value,
      offset: (dltPage.value - 1) * dltPageSize.value
    })
    dltData.value = res.items || []
    dltTotal.value = res.total || 0
  } catch (e) {
    console.error('加载大乐透失败:', e)
  }
}

// ---------- 相似度分析 ----------
const onSimLotteryChange = async () => {
  simData.value = null
  // 获取该彩种总期数
  if (simTotalMap.value[simLottery.value] == null) {
    try {
      const api = simLottery.value === 'ssq' ? listSSQData : listDLTData
      const res = await api({ limit: 1, offset: 0 })
      simTotalMap.value[simLottery.value] = res.total || 0
    } catch (e) {
      simTotalMap.value[simLottery.value] = 0
    }
  }
}

const loadSimilarity = async () => {
  simLoading.value = true
  simData.value = null
  try {
    // limit=0 不传参表示全部
    const params = simLimit.value > 0 ? simLimit.value : undefined
    const res = await getHistorySimilarity(simLottery.value, params)
    simData.value = res
    simPage.value = 1
    if (res.analyzed === 0) {
      ElMessage.warning('数据不足，至少需要 2 期才能分析')
    } else {
      ElMessage.success(`分析完成：${res.analyzed} 期，平均相似度 ${(res.summary?.avg_similarity * 100).toFixed(1)}%`)
    }
  } catch (e) {
    console.error('相似度分析失败:', e)
    ElMessage.error('分析失败：' + (e.message || '未知错误'))
  } finally {
    simLoading.value = false
  }
}

const paginatedSimItems = computed(() => {
  if (!simData.value?.items) return []
  const start = (simPage.value - 1) * simPageSize.value
  return simData.value.items.slice(start, start + simPageSize.value)
})

const distPct = (range, count) => {
  const total = Object.values(simData.value?.summary?.distribution || {}).reduce((a, b) => a + b, 0)
  if (total === 0) return 0
  return Math.round(count / total * 100)
}

const distColor = (range) => {
  if (range === '≥80%') return '#f56c6c'
  if (range === '60-80%') return '#e6a23c'
  if (range === '40-60%') return '#f0c78a'
  if (range === '20-40%') return '#409EFF'
  return '#67C23A'
}

const simProgressColor = (sim) => {
  if (sim >= 0.6) return '#f56c6c'
  if (sim >= 0.4) return '#e6a23c'
  return '#67C23A'
}

// ---------- 切换标签自动加载 ----------
watch(activeTab, (newTab) => {
  if (newTab === 'dlt' && dltData.value.length === 0) {
    loadDLT()
  }
  if (newTab === 'ssq' && ssqData.value.length === 0) {
    loadSSQ()
  }
  if (newTab === 'similarity') {
    onSimLotteryChange()
  }
})

// ---------- 生命周期 ----------
onMounted(() => {
  loadSSQ()
})
</script>

<style scoped>
.data-container {
  padding: 0;
}

.pagination-wrapper {
  margin-top: 15px;
  display: flex;
  justify-content: center;
}

.mobile-pagination {
  --el-pagination-button-size: 32px;
}

/* ===== 相似度分析样式 ===== */
.sim-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.sim-loading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 40px;
  justify-content: center;
  color: #909399;
}

.sim-summary {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.summary-card {
  flex: 1;
  min-width: 140px;
  background: #f5f7fa;
  border-radius: 10px;
  padding: 16px;
  text-align: center;
  border: 1px solid #ebeef5;
}

.summary-card.highlight {
  background: linear-gradient(135deg, #fef0f0, #fde2e2);
  border-color: #fbc4c4;
}

.summary-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
}

.summary-card.highlight .summary-value {
  color: #f56c6c;
}

.summary-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.sim-section {
  margin-bottom: 24px;
}

.sim-section-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
  padding-left: 8px;
  border-left: 3px solid #409EFF;
}

.dist-bars {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px;
}

.dist-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.dist-row:last-child {
  margin-bottom: 0;
}

.dist-label {
  width: 70px;
  font-size: 13px;
  color: #606266;
  font-weight: 500;
}

.dist-bar-track {
  flex: 1;
  height: 20px;
  background: #f0f2f5;
  border-radius: 10px;
  overflow: hidden;
}

.dist-bar {
  height: 100%;
  border-radius: 10px;
  transition: width 0.3s ease;
}

.dist-count {
  font-size: 13px;
  color: #606266;
  width: 60px;
  text-align: right;
}

.dist-pct {
  font-size: 12px;
  color: #909399;
  width: 60px;
}

.sim-ball {
  display: inline-block;
  min-width: 26px;
  height: 26px;
  line-height: 26px;
  text-align: center;
  border-radius: 50%;
  font-size: 12px;
  margin: 1px;
  font-weight: 600;
}

.ball-red {
  background: #f56c6c;
  color: #fff;
}

.ball-blue {
  background: #409EFF;
  color: #fff;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .pagination-wrapper {
    justify-content: center;
  }
  .mobile-pagination {
    --el-pagination-button-size: 40px;
  }
  .el-pagination .btn-prev,
  .el-pagination .btn-next,
  .el-pagination .el-pager li {
    min-width: 40px !important;
    height: 40px !important;
    line-height: 40px !important;
  }
  .el-pagination .el-pager li {
    font-size: 14px;
  }
  .el-table {
    font-size: 13px;
  }
  .summary-card {
    min-width: calc(50% - 8px);
  }
}
</style>
