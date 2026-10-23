<template>
  <div class="predict-container">
    <el-card>
      <template #header>🔮 生成预测</template>
      <el-form label-width="120px" label-position="top" class="predict-form">
        <el-form-item label="彩种">
          <el-radio-group v-model="lotteryType" @change="onLotteryChange">
            <el-radio value="ssq">双色球</el-radio>
            <el-radio value="dlt">大乐透</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="选择模型">
          <div class="model-select-wrapper">
            <el-select
              v-model="selectedModels"
              multiple
              placeholder="输入模型名搜索，支持多选"
              style="width:100%;"
              filterable
              collapse-tags
              collapse-tags-tooltip
              :disabled="modelOptions.length === 0"
              @change="onModelChange"
            >
              <el-option
                key="__select_all__"
                label="☑️ 全选"
                value="__select_all__"
                style="font-weight:bold;color:#409EFF;"
              />
              <el-option
                v-for="item in modelOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              >
                <div class="model-option">
                  <span class="model-option-label">{{ item.label }}</span>
                  <el-tag size="small" type="info" round class="model-option-tag">.pt</el-tag>
                </div>
              </el-option>
            </el-select>

            <div class="model-select-actions">
              <div class="model-stat">
                <span class="stat-text">本期 <strong>{{ modelOptions.length }}</strong> 个模型</span>
                <span v-if="modelPeriod" class="stat-hint">
                  （{{ modelPeriod.last_draw_date }} 开奖后训练，本期开奖 {{ modelPeriod.target_draw_date }}）
                </span>
                <span class="stat-divider">|</span>
                <span class="stat-text">已选 <strong class="selected-count">{{ selectedModels.length }}</strong> 个</span>
              </div>
              <el-button
                v-if="selectedModels.length > 0"
                size="small"
                type="danger"
                plain
                @click="clearAllSelection"
                class="clear-btn"
              >
                <el-icon><Close /></el-icon> 清空已选
              </el-button>
            </div>
          </div>
        </el-form-item>

        <el-form-item>
          <div class="btn-group">
            <!-- 一键智能预测：回测评分 → 智能选模并批量预测 → 集成融合 -->
            <el-button
              type="primary"
              size="large"
              class="smart-main-btn"
              @click="runSmartPipeline"
              :loading="smartPipelineLoading"
            >
              <el-icon v-if="!smartPipelineLoading"><MagicStick /></el-icon>
              {{ pipelineButtonText }}
            </el-button>

            <!-- 更多操作：单步功能保留，可单独执行 -->
            <el-dropdown @command="onMoreCommand" trigger="click">
              <el-button size="large" :disabled="anyActionLoading">
                更多操作<el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="agent" :disabled="agentSelectLoading">
                    ✨ 智能选择并预测
                  </el-dropdown-item>
                  <el-dropdown-item command="predict" :disabled="!selectedModels.length || loading">
                    🔮 预测已选模型（{{ selectedModels.length }}）
                  </el-dropdown-item>
                  <el-dropdown-item command="backtest" :disabled="backtestLoading">
                    📊 回测评分
                  </el-dropdown-item>
                  <el-dropdown-item command="ensemble" :disabled="ensembleLoading">
                    🎯 集成预测
                  </el-dropdown-item>
                  <el-dropdown-item command="clear" divided>🧹 清空结果</el-dropdown-item>
                  <el-dropdown-item command="refresh" :disabled="loadingModels">
                    🔄 刷新模型列表
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 集成预测结果 -->
    <el-card v-if="ensembleResult" shadow="hover" style="margin-top:20px;">
      <template #header>
        <div class="result-header">
          <span>🎯 集成预测（{{ ensembleResult.model_version }}）</span>
          <el-tag type="warning">{{ ensembleResult.forecast_date }}</el-tag>
        </div>
      </template>
      <p class="ball-row">
        <strong>红球（前区）：</strong>
        <el-tag v-for="r in ensembleResult.red" :key="'er'+r" size="large" class="result-tag">{{ r }}</el-tag>
      </p>
      <p class="ball-row">
        <strong>蓝球（后区）：</strong>
        <el-tag v-for="b in ensembleResult.blue" :key="'eb'+b" size="large" type="danger" class="result-tag">{{ b }}</el-tag>
      </p>
      <p><strong>质量评分：</strong>{{ ensembleResult.quality_score }}</p>
      <el-divider content-position="left">融合成员（权重 = 回测命中率）</el-divider>
      <el-table :data="ensembleResult.members" size="small" max-height="220">
        <el-table-column prop="model_name" label="模型" min-width="240" show-overflow-tooltip />
        <el-table-column prop="hit_total" label="回测命中率" width="110">
          <template #default="{ row }">{{ (row.hit_total * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column prop="weight" label="权重" width="90" />
      </el-table>
    </el-card>

    <!-- 模型命中率榜单 -->
    <el-card shadow="hover" style="margin-top:20px;">
      <template #header>
        <div class="result-header">
          <span>🏆 模型回测命中率榜单（{{ lotteryType === 'ssq' ? '双色球' : '大乐透' }}）</span>
          <el-button size="small" @click="loadLeaderboard(leaderboardPage)" :loading="leaderboardLoading">刷新</el-button>
        </div>
      </template>

      <!-- 加载中 -->
      <div v-if="leaderboardLoading" class="leaderboard-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>加载中...</span>
      </div>
      <!-- 空数据 -->
      <el-empty v-else-if="leaderboard.length === 0" description="暂无回测评分，请先运行回测" :image-size="80" />
      <!-- 榜单表格 + 分页（服务端分页，每次只取当前页 10 条） -->
      <template v-else>
        <el-table :data="leaderboard" size="small" max-height="360" v-loading="leaderboardLoading">
          <el-table-column type="index" label="#" width="50" :index="leaderboardIndex" />
          <el-table-column prop="model_name" label="模型" min-width="280" show-overflow-tooltip />
          <el-table-column prop="hit_red" label="红球命中" width="100">
            <template #default="{ row }">{{ (row.hit_red * 100).toFixed(1) }}%</template>
          </el-table-column>
          <el-table-column prop="hit_blue" label="蓝球命中" width="100">
            <template #default="{ row }">{{ (row.hit_blue * 100).toFixed(1) }}%</template>
          </el-table-column>
          <el-table-column prop="hit_total" label="综合" width="90">
            <template #default="{ row }">
              <el-tag :type="row.hit_total >= leaderboardTopHit ? 'success' : 'info'" size="small">
                {{ (row.hit_total * 100).toFixed(1) }}%
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="evaluated_periods" label="回测期数" width="90" />
          <el-table-column prop="updated_at" label="更新时间" width="140" />
        </el-table>
        <div class="leaderboard-pagination">
          <el-pagination
            :current-page="leaderboardPage"
            :page-size="LEADERBOARD_PAGE_SIZE"
            :total="leaderboardTotal"
            layout="total, prev, pager, next, jumper"
            size="small"
            background
            @current-change="onLeaderboardPageChange"
          />
        </div>
      </template>
    </el-card>

    <!-- 批量预测实时进度 -->
    <el-card v-if="predictProgress.active" shadow="never" style="margin-top:20px;">
      <div class="predict-progress">
        <div class="progress-info">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>正在并行推理：<strong>{{ predictProgress.done }}</strong> / {{ predictProgress.total }}</span>
          <el-tag type="success" size="small" effect="dark">✅ 成功 {{ predictProgress.success }}</el-tag>
          <el-tag v-if="predictProgress.failed > 0" type="danger" size="small" effect="dark">
            ❌ 失败 {{ predictProgress.failed }}
          </el-tag>
        </div>
        <el-progress
          :percentage="predictPercent"
          :stroke-width="16"
          :text-inside="true"
          status="success"
        />
      </div>
    </el-card>

    <div v-if="results.length > 0" style="margin-top:20px;">
      <div class="results-summary">
        <span>📋 已完成 <strong>{{ results.length }}</strong> / {{ predictProgress.total || '?' }} 个模型</span>
        <span v-if="!predictProgress.active" class="results-summary-hint">
          （每页 {{ 30 }} 个，共 {{ Math.ceil(results.length / 30) }} 页）
        </span>
      </div>
      <el-row :gutter="20">
        <el-col
          v-for="item in pagedResults"
          :key="item.modelName"
          :xs="24"
          :sm="12"
          :md="12"
          :lg="8"
        >
          <el-card class="result-card" shadow="hover">
            <template #header>
              <div class="result-header">
                <span class="model-name">{{ item.modelName }}</span>
                <el-tag :type="item.success ? 'success' : 'danger'" size="small">
                  {{ item.success ? '成功' : '失败' }}
                </el-tag>
              </div>
            </template>
            <div v-if="item.success" class="result-content">
              <p><strong>彩种：</strong>{{ item.data.lottery_type === 'ssq' ? '双色球' : '大乐透' }}</p>
              <p><strong>预测日期：</strong>{{ item.data.forecast_date }}</p>
              <p class="ball-row">
                <strong>红球（前区）：</strong>
                <el-tag
                  v-for="r in item.data.red"
                  :key="r"
                  size="default"
                  class="result-tag"
                >{{ r }}</el-tag>
              </p>
              <p class="ball-row">
                <strong>蓝球（后区）：</strong>
                <el-tag
                  v-for="b in item.data.blue"
                  :key="b"
                  size="default"
                  type="danger"
                  class="result-tag"
                >{{ b }}</el-tag>
              </p>
              <p><strong>质量评分：</strong>{{ item.data.quality_score }}</p>
            </div>
            <div v-else class="error-msg">
              <el-alert type="error" :title="item.error" show-icon />
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 分页：数千模型时只渲染当前页，控制 DOM 数量 -->
      <div v-if="results.length > 30" class="pagination-wrapper">
        <el-pagination
          v-model:current-page="resultPage"
          :page-size="30"
          :total="results.length"
          layout="total, prev, pager, next, jumper"
          size="small"
          background
        />
      </div>
    </div>

    <el-alert
      v-if="globalError"
      type="error"
      :title="globalError"
      show-icon
      closable
      @close="globalError = null"
      style="margin-top:20px;"
    />
  </div>
</template>

<script setup>
import {computed, nextTick, onMounted, onUnmounted, ref} from 'vue'
import {listModels} from '@/api/model'
import {batchPredictStream, runBacktest, getLeaderboard, ensemblePredict} from '@/api/predict'
import {ElMessage} from 'element-plus'
import {Close, MagicStick, ArrowDown, Loading} from '@element-plus/icons-vue'
import request from '@/utils/request'

const lotteryType = ref('ssq')
const selectedModels = ref([])
const modelOptions = ref([])
const modelPeriod = ref(null)  // 本期时间窗信息 {last_draw_date, target_draw_date, total_all, total}
const results = ref([])
const loading = ref(false)
const loadingModels = ref(false)
const globalError = ref(null)
const agentSelectLoading = ref(false)
const backtestLoading = ref(false)
const ensembleLoading = ref(false)
const ensembleResult = ref(null)
const leaderboard = ref([])
// 榜单服务端分页与加载状态（数千模型时每次只拉当前页 10 条）
const leaderboardLoading = ref(false)
const LEADERBOARD_PAGE_SIZE = 10
const leaderboardPage = ref(1)
const leaderboardTotal = ref(0)
const leaderboardTopHit = ref(0)
// 表格序号跨页连续
const leaderboardIndex = (i) => (leaderboardPage.value - 1) * LEADERBOARD_PAGE_SIZE + i + 1
let backtestTimer = null

// ===== 批量预测实时进度（流式）=====
const predictProgress = ref({
  active: false, total: 0, done: 0, success: 0, failed: 0
})
const predictPercent = computed(() => {
  const { done, total } = predictProgress.value
  return total > 0 ? Math.round((done / total) * 100) : 0
})
// 结果分页：数千模型时只挂载当前页卡片，避免 DOM 爆炸
const RESULT_PAGE_SIZE = 30
const resultPage = ref(1)
const pagedResults = computed(() => {
  const start = (resultPage.value - 1) * RESULT_PAGE_SIZE
  return results.value.slice(start, start + RESULT_PAGE_SIZE)
})

// ===== 一键智能预测流水线 =====
const smartPipelineLoading = ref(false)
// 当前阶段：backtest 回测评分 / select 智能选模预测 / ensemble 集成融合
const pipelineStage = ref('')

// 主按钮文字随阶段切换
const pipelineButtonText = computed(() => {
  if (pipelineStage.value === 'backtest') return '📊 回测评分中...'
  if (pipelineStage.value === 'select') return '🔮 智能选模并预测中...'
  if (pipelineStage.value === 'ensemble') return '🎯 集成融合中...'
  return '🚀 一键智能预测'
})

// 任一任务进行中时禁用"更多操作"，避免并发
const anyActionLoading = computed(() =>
  smartPipelineLoading.value || agentSelectLoading.value ||
  backtestLoading.value || ensembleLoading.value || loading.value
)

const actualModelOptions = computed(() => {
  return modelOptions.value.filter(item => item.value !== '__select_all__')
})

// ===== 修复 loadModels =====
// 调用后端 /models/list?lottery_type=xxx&current_period=true
// 后端已按"训练时间戳 >= 最近一期开奖日 00:00"过滤本期训练模型，
// 此处不再做额外前端过滤，以后端返回为准。
const loadModels = async () => {
  loadingModels.value = true
  try {
    const res = await listModels(lotteryType.value)

    // 兼容 res 或 res.data
    const data = res.data || res
    const allModels = data.models || []
    modelPeriod.value = data.period || null

    // 后端已做本期过滤（current_period=true），直接渲染。
    // 仅做文件名 → 展示 label 的格式化。
    const filtered = allModels.map(name => {
      const base = name.replace('.pt', '')
      const parts = base.split('_')
      let label = base
      if (parts.length >= 5) {
        const epochPart = parts.find(p => p.startsWith('epochs')) || ''
        const bsPart = parts.find(p => p.startsWith('bs')) || ''
        const seqPart = parts.find(p => p.startsWith('seq')) || ''
        const lrPart = parts.find(p => p.startsWith('lr')) || ''
        const timePart = parts[parts.length - 1] || ''
        label = `E${epochPart.replace('epochs','')} B${bsPart.replace('bs','')} S${seqPart.replace('seq','')} L${lrPart.replace('lr','').replace('_','.')} (${timePart})`
      }
      return { value: name, label: label }
    })
    filtered.sort((a, b) => {
      const timeA = parseInt(a.value.split('_').pop().replace('.pt','')) || 0
      const timeB = parseInt(b.value.split('_').pop().replace('.pt','')) || 0
      return timeB - timeA
    })
    modelOptions.value = filtered

    // 清除已选但不再存在的模型
    selectedModels.value = selectedModels.value.filter(m =>
      filtered.some(item => item.value === m)
    )

    if (filtered.length === 0) {
      const hint = modelPeriod.value?.last_draw_date
        ? `最近一期开奖日 ${modelPeriod.value.last_draw_date} 之后`
        : '本期'
      ElMessage.warning(`${hint}暂无训练模型，请先训练`)
    }
  } catch (e) {
    console.error('[loadModels] 加载失败:', e)
    ElMessage.error('加载模型列表失败')
  } finally {
    loadingModels.value = false
  }
}

const onLotteryChange = () => {
  selectedModels.value = []
  results.value = []
  globalError.value = null
  ensembleResult.value = null
  loadModels()
  loadLeaderboard()
}

const onModelChange = (val) => {
  const hasSelectAll = val.includes('__select_all__')
  const actualModels = actualModelOptions.value.map(item => item.value)

  if (hasSelectAll) {
    const isAllSelected = actualModels.every(m => val.includes(m))
    if (isAllSelected) {
      selectedModels.value = []
    } else {
      selectedModels.value = actualModels
    }
    const cleanVal = selectedModels.value.filter(v => v !== '__select_all__')
    selectedModels.value = cleanVal
  }
}

const clearAllSelection = () => {
  selectedModels.value = []
  ElMessage.info('已清空所有选择')
}

// ===== 回测评分：提交任务 → 轮询状态 → 刷新榜单 =====
// 轮询直到任务结束，返回 Promise；供单步按钮和一键流水线共用
// maxWaitMs：整体等待上限，防止 Celery worker 未启动时任务一直 pending 导致无限轮询
const waitBacktest = (taskId, maxWaitMs = 15 * 60 * 1000) => {
  return new Promise((resolve, reject) => {
    clearInterval(backtestTimer)
    let failCount = 0
    const startAt = Date.now()
    backtestTimer = setInterval(async () => {
      // 超过最大等待时长（worker 未启动 / 任务卡死），主动放弃
      if (Date.now() - startAt > maxWaitMs) {
        clearInterval(backtestTimer)
        reject(new Error('回测等待超时，请确认 Celery worker 已启动'))
        return
      }
      try {
        const res = await request({ url: `/train/status/${taskId}`, method: 'get' })
        failCount = 0
        if (res.status === 'completed') {
          clearInterval(backtestTimer)
          resolve(res)
        } else if (res.status === 'failed') {
          clearInterval(backtestTimer)
          reject(new Error(res.result || '回测任务失败'))
        }
      } catch (e) {
        // 单次查询异常不立即失败，连续 20 次（约 60s）才判定超时
        failCount += 1
        if (failCount >= 20) {
          clearInterval(backtestTimer)
          reject(new Error('回测状态查询超时'))
        }
      }
    }, 3000)
  })
}

// 仅提交回测任务（提交即走，不等待），返回 taskId
const submitBacktestTask = async () => {
  const res = await runBacktest(lotteryType.value, 30)
  const taskId = res.task_id || res.data?.task_id
  if (!taskId) {
    throw new Error('未返回任务 ID')
  }
  return taskId
}

// 提交回测任务并等待完成（单步"回测评分"按钮使用）
const submitBacktest = async () => {
  const taskId = await submitBacktestTask()
  ElMessage.success('回测任务已提交，正在评估所有模型...')
  const done = await waitBacktest(taskId)
  ElMessage.success(`回测完成：已评估 ${done.result?.scored ?? '全部'} 个模型`)
  await loadLeaderboard()
}

const handleBacktest = async () => {
  backtestLoading.value = true
  try {
    await submitBacktest()
  } catch (e) {
    ElMessage.error('回测失败：' + (e.response?.data?.detail || e.message || '提交失败'))
  } finally {
    backtestLoading.value = false
  }
}

const loadLeaderboard = async (page = 1) => {
  leaderboardLoading.value = true
  leaderboardPage.value = page
  try {
    const res = await getLeaderboard(lotteryType.value, page, LEADERBOARD_PAGE_SIZE)
    const rows = res.leaderboard || res.data?.leaderboard || []
    leaderboard.value = rows
    leaderboardTotal.value = res.total ?? res.data?.total ?? rows.length
    // 首页第一名即全局最高命中率，用于标签高亮
    if (page === 1 && rows.length > 0) {
      leaderboardTopHit.value = rows[0].hit_total
    }
  } catch (e) {
    console.error('[loadLeaderboard] 加载失败:', e)
  } finally {
    leaderboardLoading.value = false
  }
}

// 翻页：按页向服务端请求
const onLeaderboardPageChange = (p) => loadLeaderboard(p)

// ===== 集成预测：加权融合回测 Top-K 模型 =====
const handleEnsemble = async () => {
  ensembleLoading.value = true
  try {
    const res = await ensemblePredict(lotteryType.value, 5)
    ensembleResult.value = res.data || res
    ElMessage.success('集成预测完成')
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || '集成预测失败'
    ElMessage.error('集成预测失败：' + msg)
  } finally {
    ensembleLoading.value = false
  }
}

// ===== 批量预测（流式）：后端每完成一个模型推送一条进度，结果区实时追加 =====
const handlePredict = async () => {
  if (selectedModels.value.length === 0) {
    ElMessage.warning('请至少选择一个模型')
    return
  }

  loading.value = true
  globalError.value = null

  const allModels = selectedModels.value
  // 不预建占位卡片：数千模型时占位卡片会撑爆 DOM；进度由顶部进度条实时体现
  results.value = []
  resultPage.value = 1
  predictProgress.value = {
    active: true, total: allModels.length, done: 0, success: 0, failed: 0
  }
  let forecastDate = ''

  const applyEvent = (evt) => {
    if (evt.type === 'start') {
      forecastDate = evt.forecast_date || ''
    } else if (evt.type === 'progress') {
      predictProgress.value.done = evt.done
      if (evt.success) {
        predictProgress.value.success += 1
        // 完成一个追加一个，渲染层通过分页只挂载当前页卡片
        results.value.push({
          modelName: evt.model_name,
          success: true,
          data: {
            red: evt.red,
            blue: evt.blue,
            quality_score: evt.quality_score,
            model_version: evt.model_name,
            forecast_date: forecastDate,
            lottery_type: lotteryType.value
          }
        })
      } else {
        predictProgress.value.failed += 1
        results.value.push({
          modelName: evt.model_name,
          success: false,
          error: evt.error || '预测失败'
        })
      }
    }
  }

  try {
    const finalEvt = await batchPredictStream(lotteryType.value, allModels, applyEvent)
    const successCount = finalEvt.success_count || 0
    const failCount = finalEvt.failed_count || 0
    if (failCount === 0) {
      ElMessage.success(`全部 ${successCount} 个模型预测成功`)
    } else if (successCount > 0) {
      ElMessage.warning(`${successCount}/${allModels.length} 个模型预测成功，请查看详情`)
    } else {
      ElMessage.error('所有模型预测均失败')
    }
    // 复试方案自动生成结果提示
    const fushi = finalEvt.fushi
    if (fushi && fushi.skipped === false) {
      ElMessage.success(`复试方案已自动生成入库（${fushi.generated}/${fushi.patterns_total} 档）`)
    } else if (fushi && fushi.skipped) {
      ElMessage.warning(`复试方案未生成：${fushi.message || '当期无可用预测'}`, { duration: 5000 })
    }
  } catch (error) {
    let msg = error.message || '预测失败'
    if (error.code === 'ECONNABORTED') {
      msg = '请求超时，请稍后重试'
    } else if (error.response?.status === 404) {
      msg = '模型文件不存在，请确认模型已训练'
    }
    globalError.value = msg
    ElMessage.error('批量预测失败：' + msg)
  } finally {
    loading.value = false
    predictProgress.value.active = false
  }
}

const handleClear = () => {
  results.value = []
  globalError.value = null
}

// ===== 智能选择模型并自动预测（agent 推荐 → 兜底全选 → 批量预测）=====
// 核心流程提炼，供单步按钮和一键流水线共用
const smartSelectAndPredict = async () => {
  // 先刷新模型列表（已查所有模型，非仅本期）
  await loadModels()
  if (modelOptions.value.length === 0) {
    throw new Error('暂无可用模型，请先训练')
  }

  // 一键智能预测：使用当前彩种下所有可用模型进行批量预测
  const availableModelNames = modelOptions.value.map(item => item.value)
  selectedModels.value = availableModelNames
  ElMessage.success(`已选择全部 ${availableModelNames.length} 个模型，开始预测...`)
  await nextTick()
  await handlePredict()
}

const handleAgentSelectModels = async () => {
  if (!lotteryType.value) {
    ElMessage.warning('请先选择彩种')
    return
  }
  agentSelectLoading.value = true
  try {
    await smartSelectAndPredict()
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || '智能选择失败'
    console.error('[Agent] 错误:', e)
    ElMessage.error('智能选择失败：' + msg)
  } finally {
    agentSelectLoading.value = false
  }
}

// ===== 一键智能预测流水线：回测后台提交 → 智能选模并批量预测 → 集成融合 =====
const runSmartPipeline = async () => {
  if (smartPipelineLoading.value) return
  smartPipelineLoading.value = true
  globalError.value = null
  try {
    // 阶段 1：回测任务"提交即走"，后台异步评分，不阻塞预测与集成
    pipelineStage.value = 'backtest'
    let backtestTaskId = null
    try {
      backtestTaskId = await submitBacktestTask()
      ElMessage.info('回测任务已提交后台执行')
    } catch (e) {
      ElMessage.warning('回测提交失败：' + (e.message || ''))
    }
    await loadLeaderboard().catch(() => {})
    // 记录提交回测前是否已有评分：老用户直接用旧评分集成，新用户需等首次回测
    const hadScores = leaderboard.value.length > 0

    // 阶段 2：智能选模 + 批量并行预测（与后台回测同时进行）
    pipelineStage.value = 'select'
    await smartSelectAndPredict()

    // 阶段 3：集成预测（按回测命中率加权融合 Top-K）
    pipelineStage.value = 'ensemble'
    const doEnsemble = async () => {
      const res = await ensemblePredict(lotteryType.value, 5)
      ensembleResult.value = res.data || res
    }

    // 首次运行无评分：等后台回测跑完（已与预测并行执行了一段时间）再集成，避免无谓 400
    if (!hadScores && backtestTaskId) {
      ElMessage.info('首次运行，等待回测评分完成后进行集成融合...')
      try {
        await waitBacktest(backtestTaskId)
        await loadLeaderboard()
      } catch (e2) {
        ElMessage.warning('回测未完成：' + (e2.message || '') + '，本次跳过集成融合')
        ElMessage.success('✅ 一键智能预测完成（批量预测已生成）')
        return
      }
    }

    try {
      await doEnsemble()
      ElMessage.success('集成融合预测完成')
    } catch (e) {
      ElMessage.warning('集成预测失败：' + (e.response?.data?.detail || e.message || ''))
    }

    ElMessage.success('✅ 一键智能预测全部完成')
  } catch (e) {
    ElMessage.error('流程中断：' + (e.response?.data?.detail || e.message || '未知错误'))
  } finally {
    smartPipelineLoading.value = false
    pipelineStage.value = ''
  }
}

// "更多操作"下拉菜单命令分发
const onMoreCommand = (cmd) => {
  if (cmd === 'agent') handleAgentSelectModels()
  else if (cmd === 'predict') handlePredict()
  else if (cmd === 'ensemble') handleEnsemble()
  else if (cmd === 'backtest') handleBacktest()
  else if (cmd === 'clear') handleClear()
  else if (cmd === 'refresh') loadModels()
}

onMounted(() => {
  loadModels()
  loadLeaderboard()
})

onUnmounted(() => {
  clearInterval(backtestTimer)
})
</script>

<style scoped>
/* ... 样式保持不变 ... */
.predict-container { padding: 0; }
.predict-form .el-form-item { margin-bottom: 18px; }
.model-select-wrapper { width: 100%; }
.model-option { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.model-option-label { font-size: 13px; font-family: 'Consolas', 'Courier New', monospace; color: #303133; }
.model-option-tag { font-size: 10px; opacity: 0.7; flex-shrink: 0; }
.model-select-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  flex-wrap: wrap;
  gap: 8px;
}
.model-stat {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #909399;
}
.stat-text { color: #606266; }
.stat-text strong { color: #303133; }
.stat-text .selected-count { color: #409EFF; font-weight: 700; font-size: 15px; }
.stat-hint { color: #909399; font-size: 12px; }
.stat-divider { color: #dcdfe6; margin: 0 4px; }
.clear-btn { font-size: 12px; padding: 4px 10px; height: 28px; }
.clear-btn .el-icon { font-size: 14px; }
.btn-group .el-button--primary { min-width: 120px; }
.btn-group {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.btn-group .el-button { flex: 1 0 auto; min-width: 80px; }
/* 一键智能预测主按钮：渐变突出 */
.smart-main-btn {
  min-width: 220px;
  font-size: 16px;
  font-weight: 600;
  background: linear-gradient(135deg, #409EFF, #2b7fd4);
  border: none;
}
.smart-main-btn:hover {
  background: linear-gradient(135deg, #5cabff, #409EFF);
}
.result-card { margin-bottom: 20px; height: 100%; }
.result-header { display: flex; justify-content: space-between; align-items: center; }
.leaderboard-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 0;
  color: #909399;
  font-size: 14px;
}
.leaderboard-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.model-name { font-weight: bold; font-size: 14px; color: #303133; }
.result-content { font-size: 14px; line-height: 1.8; }
.ball-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.result-tag { margin: 2px 0; }
.error-msg { padding: 10px 0; }

/* ===== 批量预测进度 ===== */
.predict-progress { padding: 4px 2px; }
.progress-info {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  font-size: 14px;
  color: #606266;
  flex-wrap: wrap;
}
.results-summary {
  font-size: 14px;
  color: #606266;
  margin-bottom: 12px;
}
.results-summary-hint { color: #909399; font-size: 13px; margin-left: 8px; }
@media (max-width: 768px) {
  .predict-form .el-form-item { margin-bottom: 14px; }
  .result-content { font-size: 13px; }
  .result-tag { font-size: 13px; padding: 0 10px; height: 28px; }
  .model-select-actions { flex-direction: column; align-items: stretch; gap: 6px; }
  .model-stat { justify-content: center; font-size: 12px; }
  .clear-btn { align-self: center; }
  .btn-group .el-button--primary { min-width: 80px; }
  .smart-main-btn { min-width: 100%; flex: 1 0 100%; font-size: 15px; }
}
</style>