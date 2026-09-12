import { marked } from 'marked'
import katex from 'katex'
import createDOMPurify from 'dompurify'

const MARKDOWN_TAGS = [
  'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre', 'code',
  'strong', 'em', 'b', 'i', 'del', 's', 'ul', 'ol', 'li', 'table', 'thead', 'tbody',
  'tr', 'th', 'td', 'a', 'div', 'span', 'button', 'sup', 'sub'
]
const MARKDOWN_ATTRIBUTES = [
  'class', 'href', 'title', 'target', 'rel', 'type', 'aria-label', 'aria-hidden',
  'data-language', 'start', 'colspan', 'rowspan', 'align'
]
const CODE_CLASSES = new Set([
  'code-block', 'code-block__header', 'code-block__lang', 'code-block__pre',
  'code-block__footer', 'code-copy', 'copy-icon', 'copy-label', 'token-string',
  'token-comment', 'token-keyword', 'token-function', 'token-number'
])
let markdownPurifier

function getMarkdownPurifier() {
  if (!markdownPurifier) {
    markdownPurifier = createDOMPurify(window)
    markdownPurifier.addHook('uponSanitizeAttribute', (_node, attribute) => {
      if (attribute.attrName === 'class') {
        attribute.attrValue = attribute.attrValue.split(/\s+/)
          .filter(value => CODE_CLASSES.has(value) || /^language-[a-z0-9_-]+$/.test(value))
          .join(' ')
        attribute.keepAttr = Boolean(attribute.attrValue)
      }
      if (attribute.attrName === 'href') {
        const value = attribute.attrValue.trim()
        // Relative model-generated links could submit same-origin actions or spoof app routes.
        attribute.keepAttr = /^(?:https?:|mailto:)/i.test(value) && !/[\u0000-\u0020\u007f]/.test(value)
      }
    })
    markdownPurifier.addHook('afterSanitizeAttributes', node => {
      if (node.tagName === 'A') {
        node.setAttribute('target', '_blank')
        node.setAttribute('rel', 'noopener noreferrer')
      }
      if (node.tagName === 'BUTTON') node.setAttribute('type', 'button')
    })
  }
  return markdownPurifier
}

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
      '</div>',
      `<pre class="code-block__pre language-${className}"><code class="language-${className}">${highlighted}</code></pre>`,
      '<div class="code-block__footer">',
      '<button type="button" class="code-copy" aria-label="复制代码">',
      '<span class="copy-icon" aria-hidden="true">⧉</span><span class="copy-label">复制</span>',
      '</button>',
      '</div>',
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
  if (!math.length || typeof document === 'undefined') return html
  const template = document.createElement('template')
  template.innerHTML = html
  const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_TEXT)
  const textNodes = []
  while (walker.nextNode()) textNodes.push(walker.currentNode)
  for (const node of textNodes) {
    // Never interpolate generated markup into an HTML attribute or URL.
    const matches = math.filter(item => node.textContent.includes(item.marker))
    if (!matches.length) continue
    const parts = node.textContent.split(/(@@MATH_(?:BLOCK|INLINE)_\d+@@)/g)
    const fragment = document.createDocumentFragment()
    for (const part of parts) {
      const item = matches.find(value => value.marker === part)
      if (!item) {
        fragment.append(document.createTextNode(part))
      } else {
        const rendered = document.createElement('template')
        rendered.innerHTML = renderMath(item.code, item.displayMode)
        fragment.append(rendered.content)
      }
    }
    node.replaceWith(fragment)
  }
  return template.innerHTML
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
  // Without a browser DOM, fail closed as text rather than maintain a second regex sanitizer.
  if (typeof window === 'undefined' || typeof DOMParser === 'undefined') return escapeHtml(html)
  return getMarkdownPurifier().sanitize(html, {
    ALLOWED_TAGS: MARKDOWN_TAGS,
    ALLOWED_ATTR: MARKDOWN_ATTRIBUTES,
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
    FORBID_ATTR: ['style', 'id', 'name'],
    FORBID_TAGS: ['svg', 'math', 'form', 'input', 'img', 'video', 'audio'],
    SANITIZE_NAMED_PROPS: true
  })
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
  // Only KaTeX (trust:false) creates mathematical markup/styles after untrusted HTML is cleaned.
  return injectMath(sanitizeHtml(rawHtml), extracted.math)
}
