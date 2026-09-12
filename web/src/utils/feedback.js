export const workspaceConfirmOptions = {
  customClass: 'workspace-message-box',
  modalClass: 'workspace-overlay',
  cancelButtonClass: 'workspace-message-box__cancel',
  confirmButtonClass: 'workspace-message-box__confirm',
  closeOnClickModal: true,
  distinguishCancelAndClose: true
}

export const workspaceDangerConfirmOptions = {
  ...workspaceConfirmOptions,
  confirmButtonClass: 'workspace-message-box__confirm workspace-message-box__confirm--danger'
}
