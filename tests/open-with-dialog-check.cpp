// Exercise the patched KOpenWithDialog with its own application associations.
// Qt's test mode moves the KService cache, ~/Applications and the menu
// configuration under ~/.qttest, so the result does not depend on the apps or
// "Open With" bridges registered for the user.
#include <KOpenWithDialog>
#include <KSycoca>
#include <QApplication>
#include <QCheckBox>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QLabel>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QTextStream>
#include <QTreeView>

#include <memory>

static const QString TextApp = QStringLiteral("Dialog Check Text Editor");
static const QString PdfApp = QStringLiteral("Dialog Check PDF Viewer");
static const QString VideoApp = QStringLiteral("Dialog Check Video Player");

// Creates a file that must not exist yet, so an existing file is never
// overwritten. Records the path as soon as the file is created.
static bool writeNewFile(const QString &path, const QByteArray &content, QStringList &created)
{
    QDir().mkpath(QFileInfo(path).absolutePath());
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::NewOnly)) {
        return false;
    }
    created.append(path);
    return file.write(content) == content.size();
}

static QByteArray desktopEntry(const QString &name, const QByteArray &mimeTypes)
{
    return "[Desktop Entry]\nType=Application\nName=" + name.toUtf8() + "\nExec=/usr/bin/true %F\nMimeType=" + mimeTypes
        + "\nTerminal=false\n";
}

// Fixture applications in a folder unique to this run, plus a menu fragment
// with the same unique name. Only what this run created is removed.
struct Fixtures {
    std::unique_ptr<QTemporaryDir> apps;
    QStringList created;
    ~Fixtures()
    {
        for (const QString &file : std::as_const(created)) {
            QFile::remove(file);
        }
    }
};

static std::unique_ptr<Fixtures> installFixtures()
{
    auto fixtures = std::make_unique<Fixtures>();
    const QString appsRoot = QStandardPaths::writableLocation(QStandardPaths::ApplicationsLocation);
    QDir().mkpath(appsRoot);
    fixtures->apps = std::make_unique<QTemporaryDir>(appsRoot + QStringLiteral("/dolphin-open-with-dialog-check-XXXXXX"));
    if (!fixtures->apps->isValid()) {
        return nullptr;
    }
    const QString apps = fixtures->apps->path();
    const QString menu = QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation)
        + QStringLiteral("/menus/applications-merged/") + QFileInfo(apps).fileName() + QStringLiteral(".menu");
    const bool written = writeNewFile(apps + QStringLiteral("/text.desktop"), desktopEntry(TextApp, "text/plain;"), fixtures->created)
        && writeNewFile(apps + QStringLiteral("/pdf.desktop"), desktopEntry(PdfApp, "application/pdf;"), fixtures->created)
        && writeNewFile(apps + QStringLiteral("/video.desktop"), desktopEntry(VideoApp, "video/mp4;"), fixtures->created)
        // Without a menu the dialog's tree has no groups to show the apps in.
        && writeNewFile(menu, "<Menu><Name>Applications</Name><Include><All/></Include></Menu>\n", fixtures->created);
    if (!written) {
        return nullptr;
    }
    KSycoca::self()->ensureCacheValid();
    return fixtures;
}

static QStringList visibleNames(QAbstractItemModel *model, const QModelIndex &parent = {})
{
    QStringList names;
    for (int row = 0; row < model->rowCount(parent); ++row) {
        const QModelIndex index = model->index(row, 0, parent);
        if (model->hasChildren(index)) {
            names.append(visibleNames(model, index));
        } else {
            names.append(index.data().toString());
        }
    }
    return names;
}

int main(int argc, char **argv)
{
    QStandardPaths::setTestModeEnabled(true);
    QApplication app(argc, argv);
    QTextStream out(stdout), err(stderr);
    const auto fixtures = installFixtures();
    if (!fixtures) {
        err << "Could not write the test applications\n";
        return 1;
    }
    QTemporaryDir dir;
    if (!dir.isValid()) return 1;
    auto createFile = [&](const QString &name, const QByteArray &content) {
        const QString path = dir.filePath(name);
        QFile file(path);
        if (!file.open(QIODevice::WriteOnly) || file.write(content) != content.size()) return QUrl();
        return QUrl::fromLocalFile(path);
    };
    const QUrl text = createFile(QStringLiteral("sample.txt"), "hello\n");
    const QUrl text2 = createFile(QStringLiteral("second.txt"), "second\n");
    const QUrl pdf = createFile(QStringLiteral("sample.pdf"), "%PDF-1.4\n");
    const QUrl video = createFile(QStringLiteral("sample.mp4"), {});
    if (!text.isValid() || !text2.isValid() || !pdf.isValid() || !video.isValid()) return 1;

    auto check = [&](const QList<QUrl> &urls, const QString &expected, const QString &excluded, bool expectEmpty = false) {
        KOpenWithDialog dialog(urls);
        QTreeView *view = nullptr;
        for (auto *candidate : dialog.findChildren<QTreeView *>()) {
            if (QString::fromLatin1(candidate->metaObject()->className()) == QLatin1String("KApplicationView")) view = candidate;
        }
        auto *showAll = dialog.findChild<QCheckBox *>(QStringLiteral("showAllApplications"));
        if (!view || !showAll || showAll->isChecked()) {
            err << "Filtered application list or show-all toggle missing\n";
            return false;
        }
        const auto filtered = visibleNames(view->model());
        if ((!expected.isEmpty() && !filtered.contains(expected)) || filtered.contains(excluded)) {
            err << "Unexpected filtered applications for " << urls.first().fileName() << ": " << filtered.join(", ") << '\n';
            return false;
        }
        auto *emptyLabel = dialog.findChild<QLabel *>(QStringLiteral("noCompatibleApplications"));
        if (expectEmpty != (emptyLabel != nullptr) || (emptyLabel && emptyLabel->isHidden())) {
            err << "Incorrect empty-list explanation\n";
            return false;
        }
        showAll->setChecked(true);
        if (emptyLabel && !emptyLabel->isHidden()) return false;
        const auto all = visibleNames(view->model());
        if (!all.contains(TextApp) || !all.contains(PdfApp) || !all.contains(VideoApp)) {
            err << "Show-all did not restore the full application list: " << all.join(", ") << '\n';
            return false;
        }
        showAll->setChecked(false);
        if (emptyLabel && emptyLabel->isHidden()) return false;
        out << urls.first().fileName() << ": " << filtered.join(", ") << "; show-all: OK\n";
        return true;
    };
    if (!check({text}, TextApp, VideoApp)) return 1;
    if (!check({text, text2}, TextApp, VideoApp)) return 1;
    if (!check({pdf}, PdfApp, VideoApp)) return 1;
    if (!check({video}, VideoApp, TextApp)) return 1;
    if (!check({text, video}, QString(), TextApp, true)) return 1;
    return 0;
}
