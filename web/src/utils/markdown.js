import { marked } from 'marked'
import katex from 'katex'

const BLOCKED_TAGS = new Set(['script', 'style', 'iframe', 'object', 'embed'])
const URL_ATTRS = new Set(['href', 'src', 'xlink:href', 'formaction', 'action'])

const LANGUAGE_LABELS = {
  bash: 'Bash',
  shell: 'Shell',
  sh: 'Shell',
  zsh: 'Zsh',
  js: 'JavaScript',
  javascript: 'JavaScript',
  jsx: 'JSX',
  ts: 'TypeScript',
  typescript: 'TypeScript',
  tsx: 'TSX',
  json: 'JSON',
  py: 'Python',
  python: 'Python',
  html: 'HTML',
  xml: 'XML',
  css: 'CSS',
  scss: 'SCSS',
  sql: 'SQL',
  md: 'Markdown',
  markdown: 'Markdown',
  vue: 'Vue',
  text: 'Text'
}

const KEYWORDS = {
  js: ['await', 'async', 'break', 'case', 'catch', 'class', 'const', 'continue', 'debugger', 'default', 'delete', 'do', 'else', 'export', 'extends', 'finally', 'for', 'from', 'function', 'if', 'import', 'in', 'instanceof', 'let', 'new', 'of', 'return', 'static', 'super', 'switch', 'this', 'throw', 'try', 'typeof', 'var', 'void', 'while', 'with', 'yield'],
  javascript: ['await', 'async', 'break', 'case', 'catch', 'class', 'const', 'continue', 'debugger', 'default', 'delete', 'do', 'else', 'export', 'extends', 'finally', 'for', 'from', 'function', 'if', 'import', 'in', 'instanceof', 'let', 'new', 'of', 'return', 'static', 'super', 'switch', 'this', 'throw', 'try', 'typeof', 'var', 'void', 'while', 'with', 'yield'],
  jsx: ['await', 'async', 'break', 'case', 'catch', 'class', 'const', 'continue', 'debugger', 'default', 'delete', 'do', 'else', 'export', 'extends', 'finally', 'for', 'from', 'function', 'if', 'import', 'in', 'instanceof', 'let', 'new', 'of', 'return', 'static', 'super', 'switch', 'this', 'throw', 'try', 'typeof', 'var', 'void', 'while', 'with', 'yield'],
  ts: ['abstract', 'any', 'as', 'async', 'await', 'boolean', 'break', 'case', 'catch', 'class', 'const', 'constructor', 'continue', 'declare', 'default', 'delete', 'do', 'else', 'enum', 'export', 'extends', 'finally', 'for', 'from', 'function', 'if', 'implements', 'import', 'in', 'instanceof', 'interface', 'keyof', 'let', 'module', 'namespace', 'new', 'number', 'of', 'private', 'protected', 'public', 'readonly', 'return', 'static', 'string', 'super', 'switch', 'this', 'throw', 'try', 'type', 'typeof', 'var', 'void', 'while', 'with'],
  typescript: ['abstract', 'any', 'as', 'async', 'await', 'boolean', 'break', 'case', 'catch', 'class', 'const', 'constructor', 'continue', 'declare', 'default', 'delete', 'do', 'else', 'enum', 'export', 'extends', 'finally', 'for', 'from', 'function', 'if', 'implements', 'import', 'in', 'instanceof', 'interface', 'keyof', 'let', 'module', 'namespace', 'new', 'number', 'of', 'private', 'protected', 'public', 'readonly', 'return', 'static', 'string', 'super', 'switch', 'this', 'throw', 'try', 'type', 'typeof', 'var', 'void', 'while', 'with'],
  tsx: ['abstract', 'any', 'as', 'async', 'await', 'boolean', 'break', 'case', 'catch', 'class', 'const', 'constructor', 'continue', 'declare', 'default', 'delete', 'do', 'else', 'enum', 'export', 'extends', 'finally', 'for', 'from', 'function', 'if', 'implements', 'import', 'in', 'instanceof', 'interface', 'keyof', 'let', 'module', 'namespace', 'new', 'number', 'of', 'private', 'protected', 'public', 'readonly', 'return', 'static', 'string', 'super', 'switch', 'this', 'throw', 'try', 'type', 'typeof', 'var', 'void', 'while', 'with'],
  py: ['and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'False', 'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'None', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'True', 'try', 'while', 'with', 'yield'],
  python: ['and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'False', 'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'None', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'True', 'try', 'while', 'with', 'yield'],
  sql: ['ALTER', 'AND', 'AS', 'ASC', 'BETWEEN', 'BY', 'CASE', 'CREATE', 'DELETE', 'DESC', 'DISTINCT', 'DROP', 'ELSE', 'END', 'FROM', 'GROUP', 'HAVING', 'IN', 'INSERT', 'INTO', 'IS', 'JOIN', 'LEFT', 'LIKE', 'LIMIT', 'NOT', 'NULL', 'ON', 'OR', 'ORDER', 'OUTER', 'RIGHT', 'SELECT', 'SET', 'TABLE', 'THEN', 'UPDATE', 'VALUES', 'WHEN', 'WHERE'],
  bash: ['case', 'do', 'done', 'elif', 'else', 'esac', 'export', 'fi', 'for', 'function', 'if', 'in', 'then', 'while'],
  shell: ['case', 'do', 'done', 'elif', 'else', 'esac', 'export', 'fi', 'for', 'function', 'if', 'in', 'then', 'while'],
  sh: ['case', 'do', 'done', 'elif', 'else', 'esac', 'export', 'fi', 'for', 'function', 'if', 'in', 'then', 'while']
}

function escapeHtml(value = '') {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function escapeCodeHtml(value = '') {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function normalizeLanguage(language = '') {
  const raw = String(language || '').trim().split(/\s+/)[0].toLowerCase()
  return raw.replace(/[^a-z0-9_+.#-]/g, '').slice(0, 32) || 'text'
}

function languageClass(language) {
  return normalizeLanguage(language).replace(/[^a-z0-9_-]/g, '-')
}

function languageLabel(language) {
  const normalized = normalizeLanguage(language)
  return LANGUAGE_LABELS[normalized] || normalized.toUpperCase()
}

function markerFor(index) {
  // Use private-use characters only, so subsequent token regexes do not match the marker.
  let value = index
  let body = ''
  do {
    body += String.fromCharCode(0xe100 + (value % 256))
    value = Math.floor(value / 256) - 1
  } while (value >= 0)
  return `\ue000${body}\ue001`
}

function highlightWithMarkers(html, pattern, className, transforms = {}) {
  const { wrap = match => match, storage } = transforms
  return html.replace(pattern, (...args) => {
    const match = args[0]
    const marker = markerFor(storage.length)
    storage.push({ marker, html: `<span class="${className}">${wrap(match, args)}</span>` })
    return marker
  })
}

function restoreMarkers(html, storage) {
  return storage.reduce((result, item) => result.split(item.marker).join(item.html), html)
}

function keywordPattern(language) {
  const words = KEYWORDS[language]
  if (!words?.length) return null
  return new RegExp(`\\b(?:${words.map(word => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})\\b`, language === 'sql' ? 'gi' : 'g')
}

function highlightCode(code = '', language = 'text') {
  const normalizedLanguage = normalizeLanguage(language)
  let html = escapeCodeHtml(code)
  const storage = []

  const stringPattern = normalizedLanguage === 'sql'
    ? /'(?:''|\\.|[^'\\])*'|"(?:\\.|[^"\\])*"/g
    : /`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g

  html = highlightWithMarkers(html, stringPattern, 'token-string', { storage })

  if (['js', 'javascript', 'jsx', 'ts', 'typescript', 'tsx', 'css', 'scss'].includes(normalizedLanguage)) {
    html = highlightWithMarkers(html, /\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, 'token-comment', { storage })
  } else if (['py', 'python', 'bash', 'shell', 'sh', 'zsh'].includes(normalizedLanguage)) {
    html = highlightWithMarkers(html, /#[^\n]*/g, 'token-comment', { storage })
  } else if (normalizedLanguage === 'sql') {
    html = highlightWithMarkers(html, /--[^\n]*|\/\*[\s\S]*?\*\//g, 'token-comment', { storage })
  }

  if (['json'].includes(normalizedLanguage)) {
    html = highlightWithMarkers(html, /\b(?:true|false|null)\b/g, 'token-keyword', { storage })
  } else {
    const pattern = keywordPattern(normalizedLanguage)
    if (pattern) {
      html = highlightWithMarkers(html, pattern, 'token-keyword', { storage })
    }
  }

  if (['js', 'javascript', 'jsx', 'ts', 'typescript', 'tsx', 'py', 'python'].includes(normalizedLanguage)) {
    html = highlightWithMarkers(html, /\b[A-Za-z_$][\w$]*(?=\s*\()/g, 'token-function', { storage })
  }

  html = highlightWithMarkers(html, /\b-?(?:0x[\da-fA-F]+|\d+(?:\.\d+)?(?:e[+-]?\d+)?)\b/g, 'token-number', { storage })

  return restoreMarkers(html, storage)
}

function createRenderer() {
  const renderer = new marked.Renderer()

  renderer.code = function code(token, infoString) {
    const text = typeof token === 'object' && token !== null ? token.text : token
    const lang = typeof token === 'object' && token !== null ? token.lang : infoString
    const normalized = normalizeLanguage(lang)
    const className = languageClass(normalized)
    const highlighted = highlightCode(text || '', normalized)
    const label = languageLabel(normalized)

    return [
      `<div class="code-block" data-language="${escapeHtml(label)}">`,
      '<div class="code-block__header">',
      `<span class="code-block__lang">${escapeHtml(label)}</span>`,
      '<button type="button" class="code-copy" aria-label="复制代码">',
      '<span class="copy-icon" aria-hidden="true">⧉</span><span class="copy-label">复制</span>',
      '</button>',
      '</div>',
      `<pre class="code-block__pre language-${className}"><code class="language-${className}">${highlighted}</code></pre>`,
      '</div>\n'
    ].join('')
  }

  renderer.link = function link(token) {
    const href = typeof token === 'object' && token !== null ? token.href : token
    const title = typeof token === 'object' && token !== null ? token.title : arguments[1]
    const text = typeof token === 'object' && token !== null
      ? this.parser.parseInline(token.tokens || [])
      : arguments[2]

    const safeHref = escapeHtml(href || '')
    const safeTitle = title ? ` title="${escapeHtml(title)}"` : ''
    return `<a href="${safeHref}"${safeTitle} target="_blank" rel="noopener noreferrer">${text}</a>`
  }

  return renderer
}

function protectMarkdownCode(content) {
  const segments = []
  const stash = segment => {
    const marker = `@@MD_CODE_${segments.length}@@`
    segments.push(segment)
    return marker
  }

  let protectedContent = content.replace(/(^|\n)(```|~~~)[^\n]*(?:\n[\s\S]*?)?\n\2(?=\n|$)/g, match => stash(match))
  protectedContent = protectedContent.replace(/`[^`\n]+`/g, match => stash(match))

  return {
    content: protectedContent,
    restore(value) {
      return value.replace(/@@MD_CODE_(\d+)@@/g, (_, index) => segments[Number(index)] || '')
    }
  }
}

function extractMath(content) {
  const math = []
  const addMath = (code, displayMode) => {
    const marker = `@@MATH_${displayMode ? 'BLOCK' : 'INLINE'}_${math.length}@@`
    math.push({ marker, code: code.trim(), displayMode })
    return marker
  }

  let nextContent = content
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, code) => `\n\n${addMath(code, true)}\n\n`)
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, code) => `\n\n${addMath(code, true)}\n\n`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, code) => addMath(code, false))
    .replace(/(^|[^\\$])\$(?!\$)([^\n$]*?[A-Za-z\\_=^+\-*/<>{}][^\n$]*?)\$(?!\$)/g, (_, prefix, code) => `${prefix}${addMath(code, false)}`)

  return { content: nextContent, math }
}

function renderMath(code, displayMode) {
  try {
    return katex.renderToString(code, {
      displayMode,
      throwOnError: false,
      trust: false,
      strict: 'ignore'
    })
  } catch (error) {
    const tag = displayMode ? 'pre' : 'code'
    const className = displayMode ? 'math-fallback math-fallback--block' : 'math-fallback'
    return `<${tag} class="${className}">${escapeHtml(code)}</${tag}>`
  }
}

function injectMath(html, math) {
  return math.reduce((result, item) => {
    const rendered = renderMath(item.code, item.displayMode)
    let next = result

    if (item.displayMode) {
      const paragraphWrapper = new RegExp(`<p>\\s*${item.marker}\\s*</p>`, 'g')
      next = next.replace(paragraphWrapper, rendered)
    }

    return next.split(item.marker).join(rendered)
  }, html)
}

function fallbackSanitize(html) {
  return html
    .replace(/<\s*(script|style|iframe|object|embed)\b[\s\S]*?<\s*\/\s*\1\s*>/gi, '')
    .replace(/<\s*(script|style|iframe|object|embed)\b[^>]*\/?>/gi, '')
    .replace(/\s+on[a-z0-9_-]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
    .replace(/\s+(href|src|xlink:href|formaction|action)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, (match, _name, rawValue) => {
      const value = rawValue.replace(/^['"]|['"]$/g, '')
      return isJavascriptUrl(value) ? '' : match
    })
}

function normalizeUrlForSafety(value = '') {
  let normalized = String(value).trim().replace(/[\u0000-\u001f\u007f\s]+/g, '')
  try {
    normalized = decodeURIComponent(normalized)
  } catch (error) {
    // Keep the original normalized string if percent-decoding fails.
  }
  return normalized.toLowerCase()
}

export function isJavascriptUrl(value = '') {
  return normalizeUrlForSafety(value).startsWith('javascript:')
}

export function sanitizeHtml(html = '') {
  if (typeof window === 'undefined' || typeof DOMParser === 'undefined') {
    return fallbackSanitize(html)
  }

  const parser = new DOMParser()
  const doc = parser.parseFromString(`<div data-sanitizer-root>${html}</div>`, 'text/html')
  const root = doc.body.firstElementChild

  if (!root) {
    return ''
  }

  root.querySelectorAll(Array.from(BLOCKED_TAGS).join(',')).forEach(node => node.remove())

  root.querySelectorAll('*').forEach(node => {
    Array.from(node.attributes).forEach(attribute => {
      const name = attribute.name.toLowerCase()
      const value = attribute.value || ''

      if (name.startsWith('on') || name === 'srcdoc') {
        node.removeAttribute(attribute.name)
        return
      }

      if (URL_ATTRS.has(name) && isJavascriptUrl(value)) {
        node.removeAttribute(attribute.name)
        return
      }

      if (name === 'style' && /(?:javascript\s*:|expression\s*\()/i.test(value)) {
        node.removeAttribute(attribute.name)
      }
    })

    if (node.tagName?.toLowerCase() === 'a') {
      node.setAttribute('target', '_blank')
      node.setAttribute('rel', 'noopener noreferrer')
    }
  })

  return root.innerHTML
}

export function renderMarkdownWithEnhancements(text = '') {
  if (!text) {
    return ''
  }

  const protectedMarkdown = protectMarkdownCode(String(text))
  const extracted = extractMath(protectedMarkdown.content)
  const markdownContent = protectedMarkdown.restore(extracted.content)
  const rawHtml = marked.parse(markdownContent, {
    breaks: true,
    gfm: true,
    renderer: createRenderer()
  })
  const htmlWithMath = injectMath(rawHtml, extracted.math)

  return sanitizeHtml(htmlWithMath)
}
