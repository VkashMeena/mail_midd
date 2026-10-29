/**
 * AI Smart Mail Manager — Dashboard & Chart.js Visualizations
 */

document.addEventListener('DOMContentLoaded', () => {
  const chartCanvas = document.getElementById('emailActivityChart');
  if (!chartCanvas) return;

  const rawLabels = JSON.parse(chartCanvas.dataset.labels || '["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]');
  const rawData = JSON.parse(chartCanvas.dataset.values || '[28, 42, 35, 50, 44, 18, 31]');

  function getThemeColors() {
    const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
    return {
      textColor: isDark ? '#94A3B8' : '#64748B',
      gridColor: isDark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.05)',
      fillColor: isDark ? 'rgba(37, 99, 235, 0.25)' : 'rgba(37, 99, 235, 0.12)',
      borderColor: '#2563EB',
      pointBg: '#2563EB',
    };
  }

  let themeColors = getThemeColors();

  const ctx = chartCanvas.getContext('2d');
  const emailChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: rawLabels,
      datasets: [{
        label: 'Emails Received',
        data: rawData,
        borderColor: themeColors.borderColor,
        backgroundColor: themeColors.fillColor,
        borderWidth: 2.5,
        fill: true,
        tension: 0.35,
        pointBackgroundColor: themeColors.pointBg,
        pointBorderColor: '#FFFFFF',
        pointBorderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 6,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          backgroundColor: '#0F172A',
          titleColor: '#FFFFFF',
          bodyColor: '#F8FAFC',
          padding: 10,
          cornerRadius: 8,
          boxPadding: 4,
        }
      },
      scales: {
        x: {
          grid: {
            display: false,
          },
          ticks: {
            color: themeColors.textColor,
            font: {
              size: 12
            }
          }
        },
        y: {
          beginAtZero: true,
          grid: {
            color: themeColors.gridColor,
          },
          ticks: {
            color: themeColors.textColor,
            font: {
              size: 12
            },
            precision: 0
          }
        }
      }
    }
  });

  // Dynamically update Chart colors when theme changes
  window.addEventListener('themeChanged', () => {
    const updated = getThemeColors();
    emailChart.data.datasets[0].backgroundColor = updated.fillColor;
    emailChart.data.datasets[0].borderColor = updated.borderColor;
    emailChart.options.scales.x.ticks.color = updated.textColor;
    emailChart.options.scales.y.ticks.color = updated.textColor;
    emailChart.options.scales.y.grid.color = updated.gridColor;
    emailChart.update();
  });
});
