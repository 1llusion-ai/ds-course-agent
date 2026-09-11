export const learningStates = {
  unobserved: { label: '尚无记录', color: '#a8a29e' },
  recent: { label: '近期关注', color: '#0284c7' },
  needs_review: { label: '待巩固', color: '#dc6b55' },
  watching: { label: '待观察', color: '#ca8a04' },
  resolved: { label: '已克服薄弱点', color: '#16856d' }
}

export function learningStateMeta(state) {
  return learningStates[state] || learningStates.unobserved
}

export const relationTypes = {
  part_of: { label: '章节归属', color: '#a8a29e' },
  prerequisite_of: { label: '建议先学', color: '#16856d' },
  confusable_with: { label: '容易混淆', color: '#c26335' },
  related_to: { label: '相关概念', color: '#64748b' }
}

export const chapterColors = ['#3867a8', '#16856d', '#a56b24', '#547a3f', '#a34f68', '#367a9e', '#7058a3', '#b25f32', '#95822f', '#3f806d']

export function chapterColor(chapter) {
  return chapterColors[(Number(String(chapter || '').match(/\d+/)?.[0] || 1) - 1) % chapterColors.length]
}

export function neighborsOf(graph, id, enabledRelations) {
  const ids = new Set(id ? [id] : [])
  for (const edge of graph.edges) {
    if (enabledRelations.includes(edge.relation_type) && (edge.source === id || edge.target === id)) {
      ids.add(edge.source)
      ids.add(edge.target)
    }
  }
  return ids
}

export function sceneGraphData(graph) {
  const degree = new Map()
  graph.edges.forEach(edge => {
    if (edge.relation_type !== 'part_of') {
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1)
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1)
    }
  })
  const anchors = new Map(graph.chapters.map((chapter, index) => {
    const y = 1 - 2 * (index + 0.5) / graph.chapters.length
    const radius = Math.sqrt(1 - y * y)
    const angle = index * Math.PI * (3 - Math.sqrt(5))
    return [chapter.chapter, { x: Math.cos(angle) * radius * 210, y: y * 180, z: Math.sin(angle) * radius * 180 }]
  }))
  const nodes = graph.nodes.map(node => {
    const anchor = anchors.get(node.chapter)
    const chapter = node.node_type === 'chapter'
    let seed = [...node.canonical_id].reduce((value, character) => (value * 31 + character.charCodeAt(0)) >>> 0, 7)
    const offset = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return (seed / 4294967296 - 0.5) * 100 }
    return {
      id: node.canonical_id, name: node.display_name, chapter: node.chapter, kind: node.node_type,
      state: learningStates[node.learning_state] ? node.learning_state : 'unobserved', degree: degree.get(node.canonical_id) || 0,
      x: anchor.x + (chapter ? 0 : offset()), y: anchor.y + (chapter ? 0 : offset()), z: anchor.z + (chapter ? 0 : offset()),
      ...(chapter ? { fx: anchor.x, fy: anchor.y, fz: anchor.z } : {})
    }
  })
  // Force-graph mutates its nodes and edge endpoints. Never give it API objects.
  return { nodes, links: graph.edges.map(edge => ({ source: edge.source, target: edge.target, kind: edge.relation_type })) }
}

export function questionForNode(node, practice = false) {
  const context = `《数据科学导论（案例版）》${node.chapter}${node.section ? ` ${node.section} 节` : ''}的「${node.display_name}」`
  return practice
    ? `请围绕${context}出一道理解题，引导我思考，先不要给出答案。`
    : `请讲解${context}，用一个简单例子帮助我理解。`
}
