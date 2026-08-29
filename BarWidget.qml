import QtQuick
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "tdh.fantasy-feed"

  readonly property var feedService: bar && bar.shell ? bar.shell.serviceFor(moduleName) : null

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.feedService && root.feedService.loading ? "󰔟" : "󰇎"
    slotSize: Style.bar.statusSlot
    tooltipText: root.feedService && root.feedService.lastError
      ? root.feedService.lastError
      : "Fantasy Feed"
    onPressed: if (root.feedService) root.feedService.refresh()
  }
}
