import request from '@/utils/request'

/**
 * 获取今日预测分析
 * @param {string} lotteryType - 'ssq' 或 'dlt'
 */
export function getTodayAnalysis(lotteryType = 'ssq') {
  return request({
    url: '/analysis/today',
    method: 'get',
    params: { lottery_type: lotteryType }
  })
}

/**
 * 获取历史开奖自相似度分析
 * @param {string} lotteryType - 'ssq' 或 'dlt'
 * @param {number} limit - 参与分析的期数，0 表示全部
 */
export function getAnalysisSimilarity(lotteryType = 'ssq', limit = 500) {
  return request({
    url: `/data/similarity/${lotteryType}`,
    method: 'get',
    params: limit > 0 ? { limit } : {}
  })
}

// ============ 复试分析 ============

/**
 * 查询已生成的复试方案
 */
export function getFushiList(lotteryType, forecastDate = null, limit = 20) {
  return request({
    url: '/analysis/fushi/list',
    method: 'get',
    params: {
      lottery_type: lotteryType,
      forecast_date: forecastDate || undefined,
      limit
    }
  })
}

/**
 * 对某期复试方案做历史命中评估
 */
export function evaluateFushi(lotteryType, { issueNum = null, forecastDate = null } = {}) {
  const data = { lottery_type: lotteryType }
  if (issueNum != null) data.issue_num = issueNum
  if (forecastDate) data.forecast_date = forecastDate
  return request({
    url: '/analysis/fushi/evaluate',
    method: 'post',
    data
  })
}