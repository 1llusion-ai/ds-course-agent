import { CanvasTexture, Group, Mesh, MeshBasicMaterial, SphereGeometry, Sprite, SpriteMaterial } from 'three'

export function createNodeObjects() {
  const objects = new Map()
  const resources = new Set()
  const geometry = new SphereGeometry(1, 16, 12)
  const ringGeometry = new SphereGeometry(1, 12, 8)
  resources.add(geometry)
  resources.add(ringGeometry)
  function makeLabel(text, large) {
    const canvas = document.createElement('canvas')
    const context = canvas.getContext('2d')
    const font = `${large ? 600 : 400} 48px "Microsoft YaHei", "PingFang SC", sans-serif`
    context.font = font
    canvas.width = Math.ceil(context.measureText(text).width) + 28
    canvas.height = 76
    context.font = font
    context.textBaseline = 'middle'
    context.fillStyle = '#292524'
    context.shadowColor = 'rgba(255,255,255,.9)'
    context.shadowBlur = 5
    context.fillText(text, 14, 38)
    const texture = new CanvasTexture(canvas)
    const material = new SpriteMaterial({ map: texture, depthWrite: false, transparent: true })
    const sprite = new Sprite(material)
    const height = large ? 14 : 8
    sprite.scale.set(height * canvas.width / 76, height, 1)
    resources.add(texture)
    resources.add(material)
    return sprite
  }
  return {
    objects,
    create(node, color) {
      const group = new Group()
      const radius = node.kind === 'chapter' ? 5.4 : 2.1 + Math.sqrt(node.degree) * 0.4
      const material = new MeshBasicMaterial({ color, transparent: true })
      const sphere = new Mesh(geometry, material)
      sphere.scale.setScalar(radius)
      const ringMaterial = new MeshBasicMaterial({ color, transparent: true, wireframe: true, opacity: 0 })
      const ring = new Mesh(ringGeometry, ringMaterial)
      ring.scale.setScalar(radius * 1.7)
      const label = makeLabel(node.name, node.kind === 'chapter')
      label.position.y = radius + (node.kind === 'chapter' ? 10 : 7)
      group.add(sphere, ring, label)
      resources.add(material)
      resources.add(ringMaterial)
      objects.set(node.id, { group, sphere, ring, label })
      return group
    },
    dispose() {
      resources.forEach(resource => resource.dispose())
      resources.clear()
      objects.clear()
    }
  }
}
