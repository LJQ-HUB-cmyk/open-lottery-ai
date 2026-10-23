/**
 * 预测 API
 * 提供生成预测结果的功能
 */
import request from '@/utils/request'

/**
 * 生成预测
 * @param {Object} data - 预测参数
 * @param {string} data.lottery_type - 'ssq' 或 'dlt'
 * @returns {Promise} 返回预测结果 { red, blue, quality_score, model_version }
 */
export function getPrediction(data) {
  return request({
    url: '/predict/',
    method: 'post',
    data
  })
}

/**
 * 批量并行预测：一次提交多个模型，后端线程池并行推理 + 批量入库
 * @param {string} lotteryType - 'ssq' 或 'dlt'
 * @param {string[]} models - 模型文件名列表
 * @returns {Promise} 返回 { total, success_count, failed_count, results, failed }
 */
export function batchPredict(lotteryType, models) {
  return request({
    url: `/predict/batch/${lotteryType}`,
    method: 'post',
    data: { models, max_workers: 4 }
  })
}

/**
 * 批量并行预测（流式）：NDJSON 逐行推送，每完成一个模型回调一次进度事件。
 * @param {string} lotteryType - 'ssq' 或 'dlt'
 * @param {string[]} models - 模型文件名列表
 * @param {(evt: Object) => void} onEvent - 进度回调，evt.type: start/progress/done/error
 * @returns {Promise<Object>} 最终 done 事件（汇总结果）
 */
export async function batchPredictStream(lotteryType, models, onEvent) {
  const baseURL = import.meta.env.VITE_API_BASE_URL || '/api'
  // 空闲超时：流式总时长不限（模型可能很多），但连续 IDLE_TIMEOUT 无任何数据则判定卡死并取消
  const IDLE_TIMEOUT = 120000
  const controller = new AbortController()
  let idleTimer = null
  const armIdle = () => {
    if (idleTimer) clearTimeout(idleTimer)
    idleTimer = setTimeout(() => controller.abort(), IDLE_TIMEOUT)
  }
  armIdle()
  try {
    const resp = await fetch(`${baseURL}/predict/batch-stream/${lotteryType}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ models, max_workers: 16 }),
      signal: controller.signal
    })
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`
      try {
        const errBody = await resp.json()
        detail = errBody.detail || detail
      } catch (e) { /* 非 JSON 错误体，保留状态码提示 */ }
      throw new Error(detail)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let finalEvt = null
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      armIdle()  // 收到数据块，刷新空闲计时
      buffer += decoder.decode(value, { stream: true })
      // NDJSON：按行切分，最后一行可能不完整，留在 buffer 等下一块
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        const text = line.trim()
        if (!text) continue
        const evt = JSON.parse(text)
        onEvent?.(evt)
        if (evt.type === 'done') finalEvt = evt
        if (evt.type === 'error') throw new Error(evt.error || '批量预测失败')
      }
    }
    if (!finalEvt) throw new Error('流式响应异常结束，未收到完成事件')
    return finalEvt
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error('预测长时间无响应（已空闲超时），任务已自动取消，请重试')
    }
    throw e
  } finally {
    if (idleTimer) clearTimeout(idleTimer)
  }
}

/**
 * 提交回测任务
 * @param {string} lotteryType - 'ssq' 或 'dlt'
 * @param {number} nPeriods - 回测期数
 * @returns {Promise} 返回 { task_id, status, message }
 */
export function runBacktest(lotteryType, nPeriods = 30) {
  return request({
    url: `/predict/backtest/${lotteryType}?n_periods=${nPeriods}`,
    method: 'post'
  })
}

/**
 * 获取模型命中率榜单（服务端分页）
 * @param {string} lotteryType - 'ssq' 或 'dlt'
 * @param {number} page - 页码，从 1 开始
 * @param {number} pageSize - 每页条数
 * @returns {Promise} 返回 { leaderboard: 当前页行, total: 总行数, page, page_size }
 */
export function getLeaderboard(lotteryType, page = 1, pageSize = 10) {
  return request({
    url: `/predict/leaderboard/${lotteryType}`,
    method: 'get',
    params: { page, page_size: pageSize }
  })
}

/**
 * 集成预测：加权融合回测最优 Top-K 模型
 * @param {string} lotteryType - 'ssq' 或 'dlt'
 * @param {number} topK - 融合模型数
 * @returns {Promise} 返回集成预测结果
 */
export function ensemblePredict(lotteryType, topK = 5) {
  return request({
    url: `/predict/ensemble/${lotteryType}?top_k=${topK}`,
    method: 'post'
  })
}

/**
 * 双向一致性诊断：随机基线 + 严格样本外回测 + 正/反向一致性判定
 * @param {string} lotteryType - 'ssq' 或 'dlt'
 * @param {Object} [opts] - 可选参数
 * @param {number} [opts.nPeriods] - 回测期数
 * @param {number} [opts.topK] - 每个方向报告的模型数
 * @param {number} [opts.z] - 置信水平 z 值（1.96=95%）
 * @returns {Promise} 返回 { baseline, model_groups, direction_evals, consistency_check, conclusion }
 */
export function getDiagnostic(lotteryType, { nPeriods, topK = 5, z = 1.96 } = {}) {
  return request({
    url: `/predict/diagnostic/${lotteryType}`,
    method: 'get',
    // 诊断内部要跑全量回测，耗时较长，放宽超时
    timeout: 600000,
    params: {
      top_k: topK,
      z,
      ...(nPeriods ? { n_periods: nPeriods } : {})
    }
  })
}