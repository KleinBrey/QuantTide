// 买卖标记徽章的边长，单位为 CSS 像素，绘制时会按设备像素比缩放。
const BADGE_SIZE = 22;
// 价格锚点到徽章近端边缘的目标距离。
const STEM_LENGTH = 46;
// K 线价格位置上锚点圆圈的半径。
const ANCHOR_RADIUS = 3;

function roundedRect(context, x, y, width, height, radius) {
  context.beginPath();
  context.roundRect(x, y, width, height, radius);
}

class TradeMarkerRenderer {
  constructor(markers) {
    this.markers = markers;
  }

  draw(target) {
    target.useBitmapCoordinateSpace(scope => {
      const { context, bitmapSize, horizontalPixelRatio, verticalPixelRatio } = scope;
      const badgeWidth = BADGE_SIZE * horizontalPixelRatio;
      const badgeHeight = BADGE_SIZE * verticalPixelRatio;
      const radius = 4 * Math.min(horizontalPixelRatio, verticalPixelRatio);

      this.markers.forEach(marker => {
        const x = Math.round(marker.x * horizontalPixelRatio);
        const anchorY = Math.round(marker.y * verticalPixelRatio);
        const direction = marker.side === 'BUY' ? 1 : -1;
        const desiredBadgeCenterY = anchorY + direction * (STEM_LENGTH * verticalPixelRatio + badgeHeight / 2);
        const badgeCenterY = Math.min(
          bitmapSize.height - badgeHeight / 2 - 4 * verticalPixelRatio,
          Math.max(badgeHeight / 2 + 4 * verticalPixelRatio, desiredBadgeCenterY)
        );
        const badgeLeft = x - badgeWidth / 2;
        const badgeTop = badgeCenterY - badgeHeight / 2;
        const badgeEdgeY = badgeCenterY - (direction * badgeHeight) / 2;
        const color = marker.side === 'BUY' ? '#6a6a6a' : '#6a6a6a';

        context.save();

        context.beginPath();
        context.setLineDash([3 * verticalPixelRatio, 3 * verticalPixelRatio]);
        context.lineWidth = Math.max(1, verticalPixelRatio);
        context.strokeStyle = color;
        context.moveTo(x, anchorY + direction * (ANCHOR_RADIUS + 2) * verticalPixelRatio);
        context.lineTo(x, badgeEdgeY);
        context.stroke();

        context.setLineDash([]);
        context.beginPath();
        context.fillStyle = '#f8fafc';
        context.arc(x, anchorY, ANCHOR_RADIUS * verticalPixelRatio, 0, Math.PI * 2);
        context.fill();
        context.lineWidth = Math.max(1, verticalPixelRatio);
        context.strokeStyle = color;
        context.stroke();

        roundedRect(context, badgeLeft, badgeTop, badgeWidth, badgeHeight, radius);
        context.fillStyle = marker.side === 'BUY' ? '#6a6a6a' : '#6a6a6a';
        context.fill();
        context.lineWidth = Math.max(1.5, 1.5 * horizontalPixelRatio);
        context.strokeStyle = color;
        context.stroke();

        context.fillStyle = '#ffffff';
        context.font = `700 ${12 * verticalPixelRatio}px Inter, ui-sans-serif, system-ui, sans-serif`;
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillText(marker.side === 'BUY' ? 'B' : 'S', x, badgeCenterY + 0.5 * verticalPixelRatio);
        context.restore();
      });
    });
  }
}

class TradeMarkerPaneView {
  constructor(chart, series, markers) {
    this.chart = chart;
    this.series = series;
    this.markers = markers;
    this.positionedMarkers = [];
  }

  update() {
    this.positionedMarkers = this.markers.flatMap(marker => {
      const x = this.chart.timeScale().timeToCoordinate(marker.time);
      const y = this.series.priceToCoordinate(marker.price);
      if (x === null || y === null) return [];
      return [{ ...marker, x, y }];
    });
  }

  zOrder() {
    return 'top';
  }

  renderer() {
    return new TradeMarkerRenderer(this.positionedMarkers);
  }
}

export class TradeMarkerPrimitive {
  constructor(markers) {
    this.markers = markers;
    this.paneView = null;
    this.requestUpdate = null;
  }

  attached({ chart, series, requestUpdate }) {
    this.paneView = new TradeMarkerPaneView(chart, series, this.markers);
    this.requestUpdate = requestUpdate;
    this.updateAllViews();
    this.requestUpdate();
  }

  detached() {
    this.paneView = null;
    this.requestUpdate = null;
  }

  updateAllViews() {
    this.paneView?.update();
  }

  paneViews() {
    return this.paneView ? [this.paneView] : [];
  }
}
