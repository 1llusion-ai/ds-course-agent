import ElAlert from 'element-plus/es/components/alert/index.mjs'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElCard from 'element-plus/es/components/card/index.mjs'
import { ElDropdown, ElDropdownItem, ElDropdownMenu } from 'element-plus/es/components/dropdown/index.mjs'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index.mjs'
import ElIcon from 'element-plus/es/components/icon/index.mjs'
import ElInput from 'element-plus/es/components/input/index.mjs'
import ElProgress from 'element-plus/es/components/progress/index.mjs'
import ElScrollbar from 'element-plus/es/components/scrollbar/index.mjs'
import ElSegmented from 'element-plus/es/components/segmented/index.mjs'
import { ElOption, ElSelect } from 'element-plus/es/components/select/index.mjs'
import ElSkeleton from 'element-plus/es/components/skeleton/index.mjs'
import ElSwitch from 'element-plus/es/components/switch/index.mjs'

const components = {
  ElAlert,
  ElButton,
  ElCard,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElOption,
  ElProgress,
  ElScrollbar,
  ElSegmented,
  ElSelect,
  ElSkeleton,
  ElSwitch
}

export function installElementPlus(app) {
  for (const [name, component] of Object.entries(components)) {
    app.component(name, component)
  }
}
