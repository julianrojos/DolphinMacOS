// Reports two separate things:
// 1. The applications in KService's menu tree, filtered like the "Open With"
//    dialog (hidden entries and separators excluded) - what that dialog lists.
// 2. For each MIME type given, whether Qt knows it and which applications
//    KService offers for it - what Dolphin's "Open With" submenu lists.
// Exit code 1 if the tree has no visible application or a type is unknown or
// has no application.
#include <KApplicationTrader>
#include <KServiceGroup>
#include <QCoreApplication>
#include <QMimeDatabase>
#include <QTextStream>

static int countVisibleApps(const KServiceGroup::Ptr &group, const QString &path, QTextStream &out)
{
    int count = 0;
    // Same filters as the dialog: sorted, exclude NoDisplay, no separators.
    for (const KSycocaEntry::Ptr &entry : group->entries(true, true, false)) {
        if (entry->isType(KST_KServiceGroup)) {
            const KServiceGroup::Ptr child(static_cast<KServiceGroup *>(entry.data()));
            if (child->noDisplay()) {
                continue;
            }
            count += countVisibleApps(child, path + QLatin1Char('/') + child->caption(), out);
        } else if (entry->isType(KST_KService)) {
            const KService::Ptr service(static_cast<KService *>(entry.data()));
            if (service->isApplication() && !service->noDisplay()) {
                out << "  " << path << ": " << service->name() << '\n';
                ++count;
            }
        }
    }
    return count;
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QTextStream out(stdout);
    int status = 0;

    out << "Menu tree (\"Other Application...\" dialog):\n";
    const KServiceGroup::Ptr root = KServiceGroup::root();
    const int visible = (root && root->isValid()) ? countVisibleApps(root, QString(), out) : 0;
    out << "Visible applications in tree: " << visible << '\n';
    if (visible == 0) {
        status = 1;
    }

    const QStringList types = app.arguments().mid(1);
    for (const QString &type : types) {
        const QMimeType mime = QMimeDatabase().mimeTypeForName(type);
        QStringList names;
        for (const KService::Ptr &service : KApplicationTrader::queryByMimeType(type)) {
            names << service->name();
        }
        out << type << ": " << (mime.isValid() ? "known" : "UNKNOWN") << "; apps: "
            << (names.isEmpty() ? QStringLiteral("NONE") : names.join(QStringLiteral(", "))) << '\n';
        if (!mime.isValid() || names.isEmpty()) {
            status = 1;
        }
    }
    return status;
}
