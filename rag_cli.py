"""Terminal entry point for Phase 2: index, ask, compare policy versions."""
import argparse
from datetime import date
from database.db import ROOT
from rag.policies import load_policies
from rag.chunks import split_policy


def main():
    parser = argparse.ArgumentParser(description='HR Policy RAG assistant')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('index', help='Rebuild local Chroma index from registered policy files')
    ask_parser = sub.add_parser('ask', help='Ask policy question with citations')
    ask_parser.add_argument('question')
    ask_parser.add_argument('--date', default=date.today().isoformat(), help='Policy as-of date YYYY-MM-DD')
    args = parser.parse_args()
    index_dir = ROOT / 'data' / 'chroma'
    if args.command == 'index':
        from rag.store import rebuild
        chunks = [chunk for policy in load_policies() for chunk in split_policy(policy)]
        print(f'Indexed {rebuild(chunks, index_dir)} policy chunks from {len(load_policies())} policies.')
    else:
        from rag.assistant import ask
        result = ask(args.question, on=date.fromisoformat(args.date), index_dir=index_dir)
        print('\nANSWER\n' + result['answer'])
        for source in result['sources']:
            page_info = f"Page {source.get('page', 1)}, " if source.get('page') else ""
            print(f'[{source["marker"]}] {source["title"]} v{source["version"]} — {source["section"]} ({page_info}File: {source["file"]})')
        for warning in result['warnings']:
            print('WARNING:', warning)

if __name__ == '__main__':
    main()
