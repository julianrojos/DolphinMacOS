#include <QCoreApplication>
#include <QEventLoop>
#include <QList>
#include <QTimer>
#include <QUrl>

#include <iostream>

namespace DolphinQuickLook
{
bool visible = false;
QList<QUrl> displayed;
bool isVisible(const void *) { return visible; }
void update(const QList<QUrl> &urls, const void *)
{
    displayed = urls;
    if (urls.isEmpty()) {
        visible = false;
    }
}
void close(const void *) { visible = false; }
}

class DolphinMainWindow : public QObject
{
public:
    quint64 m_quickLookSelectionGeneration = 0;
    QList<QUrl> selected;
    QList<QUrl> localSelectedUrls() const { return selected; }
    void updateQuickLook();
    void closeQuickLook();
};

#include "quicklook-selection-methods.inc"

static void waitFor(int milliseconds)
{
    QEventLoop loop;
    QTimer::singleShot(milliseconds, &loop, &QEventLoop::quit);
    loop.exec();
}

static bool check(bool condition, const char *message)
{
    if (!condition) {
        std::cerr << message << '\n';
    }
    return condition;
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    DolphinMainWindow window;
    const QUrl first = QUrl::fromLocalFile(QStringLiteral("/tmp/first"));
    const QUrl second = QUrl::fromLocalFile(QStringLiteral("/tmp/second"));
    DolphinQuickLook::visible = true;
    window.selected = {first};
    window.updateQuickLook();
    window.selected.clear();
    window.updateQuickLook();
    waitFor(100);
    window.selected = {second};
    window.updateQuickLook();
    waitFor(400);
    if (!check(DolphinQuickLook::visible && DolphinQuickLook::displayed == QList<QUrl>{second},
               "A transient empty selection must not close or overwrite the new preview")) {
        return 1;
    }
    window.selected.clear();
    window.updateQuickLook();
    waitFor(400);
    if (!check(!DolphinQuickLook::visible, "A persistent empty selection must close the preview")) {
        return 1;
    }
    DolphinQuickLook::visible = true;
    window.updateQuickLook();
    window.closeQuickLook();
    DolphinQuickLook::visible = true;
    window.selected = {first};
    window.updateQuickLook();
    waitFor(400);
    if (!check(DolphinQuickLook::visible && DolphinQuickLook::displayed == QList<QUrl>{first},
               "An old timer must not close a reopened preview")) {
        return 1;
    }
    std::cout << "Quick Look selection timing: OK\n";
    return 0;
}
